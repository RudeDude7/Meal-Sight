"""POST /api/cook — the cook-confirmation flow. This is the ONLY path
in this whole API that mutates meal history and deducts from the
pantry — generate_output (agent node 9) deliberately never calls
remove_items (see its own module docstring), and log_meal itself is
documented, at the MCP layer, to fire only after cooking is actually
confirmed. This endpoint is that confirmation.

ORDERING AND PARTIAL-FAILURE BEHAVIOR (a real decision, not an
accident): log_meal runs FIRST, remove_items SECOND. There is no shared
transaction across the two servers — user_intelligence and
pantry_manager are separate SQLite databases behind separate MCP
subprocesses — so a failure between the two calls is a real
possibility this endpoint has to have an opinion about, not paper over.

Reasoning: a real cooking event is the more important fact to never
lose. meal_history feeds cuisine_preferences, protein_preference, and
check_repetition — every one of those shapes FUTURE recommendations,
and there is no way to retroactively notice "a log_meal call silently
never happened" and repair it later; the gap just persists forever,
quietly, until a much later WTF moment (or never). A stale pantry, by
contrast, is a small, visible, self-correcting problem — it overstates
what's actually on hand until the user's next photo update or a manual
PATCH /api/pantry correction, or until this endpoint itself is called
again on a fresh idempotency window.

THE INCONSISTENCY THIS ACCEPTS, STATED PLAINLY: if remove_items (or the
get_pantry/match_ingredients calls that feed it) fails AFTER log_meal
has already succeeded, this endpoint still returns a 200 — the meal WAS
genuinely cooked and IS genuinely logged — with pantry_deduction_error
set to a real, specific message, and deducted left empty (or partial,
if some items were removed before a later one failed). The pantry may
then overstate what's really left until corrected. If log_meal ITSELF
fails, nothing is returned as a success at all — the whole request
raises (a real 4xx/5xx), and it's safe to retry, because nothing was
recorded and nothing was deducted.

IDEMPOTENCY (mealsight.api.idempotency, see its own module docstring
for the full reasoning): a client-supplied idempotency_key, or one
derived from recipe_id + a coarse time window when omitted. A repeat
call with the same key returns the EXACT response the first call
computed, including a partial-failure one — this endpoint never
silently retries a failed deduction under the same key, since
remove_items isn't naturally safe to call twice for the same items.

INGREDIENT DERIVATION: when the caller doesn't supply ingredients_used,
this endpoint derives them itself — fresh, at cook time, from the
CURRENT pantry (get_pantry) and a fresh match_ingredients call, never
from whatever a possibly-stale earlier recommendation response said.
Whichever names are actually used (caller-supplied or derived), every
one is validated against the recipe's OWN real ingredient list (get_
recipe) before ever reaching remove_items — an ingredient the recipe
didn't call for, or one the pantry doesn't currently have, is skipped
and reported, never silently deducted or silently errored.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from mealsight.agent.mcp_client import MCPClientManager
from mealsight.api.dependencies import IdempotencyDep, MCPManagerDep
from mealsight.api.errors import APIError
from mealsight.api.idempotency import derive_idempotency_key
from mealsight.api.mcp_proxy import unwrap_mcp_result
from mealsight.matching.normalize import normalize_ingredient
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.api.cook")

router = APIRouter(prefix="/api/cook", tags=["cook"])


class CookRequest(BaseModel):
    recipe_id: str
    servings_made: int
    ingredients_used: list[str] | None = None
    rating: int | None = None
    idempotency_key: str | None = None


def _validate_request(body: CookRequest) -> None:
    if body.servings_made <= 0:
        raise APIError(400, "invalid_servings", "servings_made must be a positive integer.")
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise APIError(400, "invalid_rating", "rating must be an integer from 1 to 5.")


async def _candidate_ingredient_names(
    manager: MCPClientManager, body: CookRequest, pantry_items: list[dict[str, Any]]
) -> list[str]:
    if body.ingredients_used:
        return body.ingredients_used
    match_result = unwrap_mcp_result(
        await manager.call_tool(
            "recipe_engine",
            "match_ingredients",
            {
                "recipe_id": body.recipe_id,
                "available_ingredients": [item["name"] for item in pantry_items],
            },
        )
    )
    return [item["name"] for item in match_result.get("matched_items", []) if item.get("name")]


async def _deduct_pantry(
    manager: MCPClientManager, body: CookRequest, recipe: dict[str, Any], recipe_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Returns (deducted, skipped, error). Never raises — a failure here
    is reported in the returned error string, not propagated, since by
    the time this runs log_meal has already succeeded (see this
    module's own docstring on why that ordering is deliberate)."""
    deducted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        pantry = unwrap_mcp_result(await manager.call_tool("pantry_manager", "get_pantry", {}))
        pantry_items = pantry.get("items", [])
        pantry_names = {normalize_ingredient(item["name"]) for item in pantry_items if item.get("name")}

        candidate_names = await _candidate_ingredient_names(manager, body, pantry_items)

        recipe_index = {
            normalize_ingredient(ingredient["name"]): ingredient
            for ingredient in recipe.get("ingredients", [])
            if ingredient.get("name")
        }
        servings_base = recipe.get("servings_base") or body.servings_made
        scale_factor = (body.servings_made / servings_base) if servings_base else 1.0

        to_remove: list[dict[str, Any]] = []
        for name in candidate_names:
            key = normalize_ingredient(name)
            recipe_ingredient = recipe_index.get(key)
            if recipe_ingredient is None:
                # Never deduct something the recipe did not use.
                skipped.append({"name": name, "reason": "not_in_recipe"})
                continue
            if key not in pantry_names:
                # Never deduct an item the pantry does not have.
                skipped.append({"name": name, "reason": "not_in_pantry"})
                continue
            quantity = recipe_ingredient.get("quantity")
            if quantity is None:
                skipped.append({"name": name, "reason": "quantity_unknown"})
                continue
            to_remove.append(
                {"name": recipe_ingredient["name"], "quantity_used": round(quantity * scale_factor, 4)}
            )

        if to_remove:
            removal = unwrap_mcp_result(
                await manager.call_tool(
                    "pantry_manager",
                    "remove_items",
                    {"items": to_remove, "recipe_name": recipe_name},
                )
            )
            for detail in removal.get("details", []):
                quantity_removed = detail.get("quantity_removed", 0.0)
                quantity_remaining = detail.get("quantity_remaining", 0.0)
                deducted.append(
                    {
                        "name": detail.get("name"),
                        "before": round(quantity_remaining + quantity_removed, 4),
                        "after": quantity_remaining,
                        "quantity_removed": quantity_removed,
                    }
                )
        return deducted, skipped, None
    except APIError as exc:
        logger.error("cook_pantry_deduction_failed", recipe_id=body.recipe_id, error=exc.message)
        return deducted, skipped, exc.message


async def _perform_cook(manager: MCPClientManager, body: CookRequest) -> dict[str, Any]:
    recipe = unwrap_mcp_result(
        await manager.call_tool("recipe_engine", "get_recipe", {"recipe_id": body.recipe_id})
    )
    recipe_name = recipe.get("name", body.recipe_id)

    preferences_before = None
    if body.rating is not None:
        preferences_before = unwrap_mcp_result(
            await manager.call_tool("user_intelligence", "get_user_profile", {})
        )

    # log_meal FIRST — see this module's own docstring for why.
    meal = unwrap_mcp_result(
        await manager.call_tool(
            "user_intelligence",
            "log_meal",
            {
                "recipe_id": body.recipe_id,
                "recipe_name": recipe_name,
                "cuisine": recipe.get("cuisine"),
                "meal_type": recipe.get("meal_type"),
                "date": date.today().isoformat(),
                "rating": body.rating,
                "servings_made": body.servings_made,
                "ingredients_used": body.ingredients_used,
                "notes": None,
            },
        )
    )

    preferences_after = None
    if body.rating is not None:
        preferences_after = unwrap_mcp_result(
            await manager.call_tool("user_intelligence", "get_user_profile", {})
        )

    # remove_items SECOND — its own failure never loses the meal record above.
    deducted, skipped, pantry_deduction_error = await _deduct_pantry(manager, body, recipe, recipe_name)

    return {
        "meal": meal,
        "deducted": deducted,
        "skipped": skipped,
        "preferences_before": preferences_before,
        "preferences_after": preferences_after,
        "pantry_deduction_error": pantry_deduction_error,
    }


@router.post("")
async def cook(body: CookRequest, manager: MCPManagerDep, idempotency: IdempotencyDep) -> dict[str, Any]:
    _validate_request(body)

    key = body.idempotency_key or derive_idempotency_key(body.recipe_id)

    async def _compute() -> dict[str, Any]:
        return await _perform_cook(manager, body)

    response, was_replayed = await idempotency.run_once(key, _compute)
    return {**response, "idempotent_replay": was_replayed}
