"""generate_output — builds the concrete, actionable artifacts around
top_recommendation and assembles final_response, the text a person
actually reads.

When a recipe was chosen (top_recommendation["available"] is True):
get_recipe (full ingredients/steps), scale_recipe (sized to the
requested servings — unified_request.servings, falling back to the
recipe's own servings_base when the user never stated one),
find_substitutions for whatever's still missing and not already
resolved by match_rank's own table-driven substitutable_items, and
pantry_manager's create_grocery_list for whatever's genuinely missing.
nutrition_info is NOT recalculated here — match_rank (node 7) already
computed it, per-serving, for this exact recipe; reusing it avoids a
redundant MCP call.

When nothing was cookable (top_recommendation["available"] is False):
no scale_recipe/get_recipe call at all — there's no chosen recipe to
scale — but still builds a grocery list, for the CLOSEST candidate
match_rank/reason already identified, so reason's own shopping-list
explanation comes with something the user can actually act on rather
than just a naming of what's missing.

IMPORTANT boundary this node respects: remove_items is never called
here, or anywhere in this graph. The pantry is only ever deducted after
cooking is actually confirmed, through a separate, later, user-
confirmed flow outside this graph entirely — the same boundary
record_outcome (node 10, formerly log_learn) respects for log_meal.

Every real MCP step here is independently wrapped so one failing never
blocks the others, and final_response is built from whatever succeeded
— this node's own contract is the same "never raise, always return
something usable" every node in this graph already follows.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.generate_output")

NODE_NAME = "generate_output"

# How many still-missing ingredients get an explicit find_substitutions
# lookup — capped so one very sparse pantry doesn't turn into a dozen
# extra MCP calls for one response.
SUBSTITUTION_LOOKUP_LIMIT = 5

_DIMENSION_LABELS: dict[str, str] = {
    "ingredient_match_reasoning": "Ingredients",
    "freshness_reasoning": "Freshness",
    "nutrition_reasoning": "Nutrition",
    "variety_reasoning": "Variety",
    "context_reasoning": "Context",
    "taste_reasoning": "Taste",
}


def _find_matched_entry(matched_recipes: list[dict[str, Any]], recipe_id: str) -> dict[str, Any] | None:
    for entry in matched_recipes:
        if entry.get("recipe_id") == recipe_id:
            return entry
    return None


async def _fetch_get_recipe(runtime: Runtime[AgentContext], recipe_id: str) -> dict[str, Any] | None:
    result = await runtime.context.mcp.call_tool("recipe_engine", "get_recipe", {"recipe_id": recipe_id})
    if result.success and isinstance(result.data, dict) and "error" not in result.data:
        return result.data
    logger.warning("generate_output_get_recipe_failed", recipe_id=recipe_id, error=result.error)
    return None


async def _fetch_scale_recipe(
    runtime: Runtime[AgentContext], recipe_id: str, target_servings: int
) -> dict[str, Any] | None:
    result = await runtime.context.mcp.call_tool(
        "recipe_engine", "scale_recipe", {"recipe_id": recipe_id, "target_servings": target_servings}
    )
    if result.success and isinstance(result.data, dict) and "error" not in result.data:
        return result.data
    logger.warning("generate_output_scale_recipe_failed", recipe_id=recipe_id, error=result.error)
    return None


async def _fetch_substitutions(
    runtime: Runtime[AgentContext], missing_items: list[Any], already_substituted: set[str]
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in missing_items
        if isinstance(item, dict) and item.get("name") and item["name"] not in already_substituted
    ][:SUBSTITUTION_LOOKUP_LIMIT]

    suggestions: list[dict[str, Any]] = []
    for item in candidates:
        result = await runtime.context.mcp.call_tool(
            "recipe_engine",
            "find_substitutions",
            {"ingredient_name": item["name"], "reason": "unavailable"},
        )
        if result.success and isinstance(result.data, dict) and "error" not in result.data:
            suggestions.append(result.data)
        else:
            logger.warning(
                "generate_output_find_substitutions_failed", ingredient=item["name"], error=result.error
            )
    return suggestions


async def _fetch_grocery_list(
    runtime: Runtime[AgentContext], recipe_id: str, recipe_name: str, missing_items: list[Any]
) -> dict[str, Any] | None:
    ingredients = [
        {
            "name": item.get("name"),
            "quantity": None,
            "unit": None,
            "importance": item.get("importance", "important"),
        }
        for item in missing_items
        if isinstance(item, dict) and item.get("name")
    ]
    if not ingredients:
        return None

    result = await runtime.context.mcp.call_tool(
        "pantry_manager",
        "create_grocery_list",
        {
            "missing_by_recipe": [
                {"recipe_id": recipe_id, "recipe_name": recipe_name, "missing_ingredients": ingredients}
            ]
        },
    )
    if result.success and isinstance(result.data, dict) and "error" not in result.data:
        return result.data
    logger.warning("generate_output_create_grocery_list_failed", recipe_id=recipe_id, error=result.error)
    return None


def _format_dimension_reasoning(reasoning: dict[str, Any] | None) -> str:
    if not reasoning:
        return ""
    lines = []
    for key, label in _DIMENSION_LABELS.items():
        dimension = reasoning.get(key)
        if isinstance(dimension, dict) and dimension.get("applies"):
            lines.append(f"- {label}: {dimension.get('reasoning')}")
    return "\n".join(lines)


def _format_grocery_list(grocery_list: dict[str, Any] | None) -> list[str]:
    if not grocery_list:
        return []
    lines = ["", "Grocery list:"]
    for section in grocery_list.get("sections") or []:
        lines.append(f"{section.get('section', 'Other')}:")
        for item in section.get("items") or []:
            lines.append(f"  - {item.get('name')}")
    return lines


def _format_available_response(
    *,
    detail: dict[str, Any] | None,
    scaled: dict[str, Any] | None,
    nutrition_info: dict[str, Any] | None,
    matched_entry: dict[str, Any] | None,
    substitutions: list[dict[str, Any]],
    grocery_list: dict[str, Any] | None,
    top_recommendation: dict[str, Any],
    target_servings: int,
) -> str:
    name = (detail or {}).get("name") or (matched_entry or {}).get("name") or "the recommended recipe"
    lines = [f"# {name}"]

    cook_time = (scaled or {}).get("cook_time_minutes") or (detail or {}).get("cook_time_minutes")
    if cook_time:
        note = f" ({scaled.get('cook_time_note')})" if scaled and scaled.get("cook_time_adjusted") else ""
        lines.append(f"Cook time: {cook_time} minutes{note}")

    if scaled and scaled.get("ingredients"):
        lines.append(f"\nIngredients (for {scaled.get('target_servings', target_servings)} servings):")
        for ing in scaled["ingredients"]:
            unit = f" {ing['unit']}" if ing.get("unit") else ""
            lines.append(f"- {ing.get('quantity_display', '')}{unit} {ing.get('name', '')}".strip())
    elif detail and detail.get("ingredients"):
        lines.append(f"\nIngredients (base recipe, {detail.get('servings_base')} servings):")
        for ing in detail["ingredients"]:
            unit = f" {ing['unit']}" if ing.get("unit") else ""
            qty = ing["quantity"] if ing.get("quantity") is not None else ""
            lines.append(f"- {qty}{unit} {ing.get('name', '')}".strip())

    if detail and detail.get("steps"):
        lines.append("\nSteps:")
        for i, step in enumerate(detail["steps"], start=1):
            lines.append(f"{i}. {step}")

    match_score = (matched_entry or {}).get("match_score")
    if match_score is not None:
        lines.append(f"\nIngredient match: {match_score}")

    missing = (matched_entry or {}).get("missing_items") or []
    if missing:
        names = ", ".join(str(m.get("name", m)) if isinstance(m, dict) else str(m) for m in missing)
        lines.append(f"Missing: {names}")

    substitutable = (matched_entry or {}).get("substitutable_items") or []
    if substitutable:
        subs_text = "; ".join(f"{s.get('substitute')} for {s.get('original')}" for s in substitutable)
        lines.append(f"Already-known substitutes: {subs_text}")

    if substitutions:
        lines.append("\nIf you're missing something, try:")
        for sub in substitutions:
            top_pick = (sub.get("suggestions") or [None])[0]
            if top_pick:
                lines.append(
                    f"- {sub.get('ingredient')}: try {top_pick.get('substitute')} "
                    f"({top_pick.get('flavor_impact')} flavor impact)"
                )

    if nutrition_info:
        coverage_note = nutrition_info.get("coverage_note", "")
        lines.append(
            f"\nNutrition (per serving): {nutrition_info.get('calories')} cal, "
            f"{nutrition_info.get('protein_g')}g protein, {nutrition_info.get('carbs_g')}g carbs, "
            f"{nutrition_info.get('fat_g')}g fat. {coverage_note}"
        )

    lines.extend(_format_grocery_list(grocery_list))

    reasoning_text = _format_dimension_reasoning(top_recommendation.get("reasoning"))
    if reasoning_text:
        lines.append(f"\nWhy this recipe:\n{reasoning_text}")

    overall_summary = top_recommendation.get("overall_summary")
    if overall_summary:
        lines.append(f"\n{overall_summary}")

    return "\n".join(lines)


def _format_unavailable_response(
    top_recommendation: dict[str, Any], grocery_list: dict[str, Any] | None
) -> str:
    explanation = top_recommendation.get("explanation", "No recommendation was reached this run.")
    lines = [explanation]
    if grocery_list:
        lines.append("\nTo make the closest option work, you'd need:")
        for section in grocery_list.get("sections") or []:
            for item in section.get("items") or []:
                lines.append(f"- {item.get('name')}")
    return "\n".join(lines)


async def _build_unavailable_response(
    state: MealSightState, runtime: Runtime[AgentContext], top_recommendation: dict[str, Any]
) -> dict[str, Any]:
    messages: list[str] = []
    grocery_list: dict[str, Any] | None = None
    try:
        matched_recipes = state.get("matched_recipes") or []
        if matched_recipes:
            closest = matched_recipes[0]
            grocery_list = await _fetch_grocery_list(
                runtime,
                closest.get("recipe_id", ""),
                closest.get("name", "closest option"),
                closest.get("missing_items") or [],
            )
            if grocery_list:
                messages.append(f"[{NODE_NAME}] Built a grocery list for the closest option.")
    except Exception:
        logger.error("generate_output_unavailable_path_failed", exc_info=True)

    final_response = _format_unavailable_response(top_recommendation, grocery_list)
    messages.append(f"[{NODE_NAME}] Prepared a shopping list instead of a recommendation.")

    update: dict[str, Any] = {"final_response": final_response, "stream_messages": messages}
    if grocery_list:
        update["grocery_list"] = grocery_list
    return update


async def _build_available_response(
    state: MealSightState, runtime: Runtime[AgentContext], top_recommendation: dict[str, Any]
) -> dict[str, Any]:
    messages: list[str] = []
    recipe_id = top_recommendation.get("recipe_id", "")
    matched_entry = _find_matched_entry(state.get("matched_recipes") or [], recipe_id)
    unified = state.get("unified_request")

    detail: dict[str, Any] | None = None
    try:
        detail = await _fetch_get_recipe(runtime, recipe_id)
        if detail:
            messages.append(f"[{NODE_NAME}] Got the full recipe for {detail.get('name', recipe_id)}.")
    except Exception:
        logger.error("generate_output_get_recipe_unexpected_failure", exc_info=True)

    target_servings = 0
    if unified is not None and unified.servings:
        target_servings = unified.servings
    elif detail is not None and detail.get("servings_base"):
        target_servings = detail["servings_base"]
    target_servings = target_servings or 1

    scaled: dict[str, Any] | None = None
    try:
        scaled = await _fetch_scale_recipe(runtime, recipe_id, target_servings)
        if scaled:
            messages.append(f"[{NODE_NAME}] Scaled the recipe to {target_servings} serving(s).")
    except Exception:
        logger.error("generate_output_scale_recipe_unexpected_failure", exc_info=True)

    missing_items = (matched_entry or {}).get("missing_items") or []
    substitutable_items = (matched_entry or {}).get("substitutable_items") or []
    already_substituted = {
        str(s["original"]) for s in substitutable_items if isinstance(s, dict) and s.get("original")
    }

    substitutions: list[dict[str, Any]] = []
    try:
        substitutions = await _fetch_substitutions(runtime, missing_items, already_substituted)
        if substitutions:
            messages.append(
                f"[{NODE_NAME}] Found substitution ideas for {len(substitutions)} missing ingredient(s)."
            )
    except Exception:
        logger.error("generate_output_find_substitutions_unexpected_failure", exc_info=True)

    grocery_list: dict[str, Any] | None = None
    try:
        recipe_name = (detail or matched_entry or {}).get("name", recipe_id)
        grocery_list = await _fetch_grocery_list(runtime, recipe_id, recipe_name, missing_items)
        if grocery_list:
            messages.append(f"[{NODE_NAME}] Built a grocery list for what's missing.")
    except Exception:
        logger.error("generate_output_create_grocery_list_unexpected_failure", exc_info=True)

    nutrition_info = (matched_entry or {}).get("nutrition_info")

    final_response = _format_available_response(
        detail=detail,
        scaled=scaled,
        nutrition_info=nutrition_info,
        matched_entry=matched_entry,
        substitutions=substitutions,
        grocery_list=grocery_list,
        top_recommendation=top_recommendation,
        target_servings=target_servings,
    )
    messages.append(f"[{NODE_NAME}] Built the full response.")

    update: dict[str, Any] = {"final_response": final_response, "stream_messages": messages}
    if scaled:
        update["scaled_recipe"] = scaled
    if grocery_list:
        update["grocery_list"] = grocery_list
    if nutrition_info:
        update["nutrition_info"] = nutrition_info
    return update


async def generate_output(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    top_recommendation = state.get("top_recommendation")
    if top_recommendation is None:
        logger.info("node_finished", node=NODE_NAME, reason="no top_recommendation")
        return {
            "final_response": "No recommendation was reached this run.",
            "stream_messages": [f"[{NODE_NAME}] Nothing to build a response from."],
        }

    try:
        if not top_recommendation.get("available"):
            result = await _build_unavailable_response(state, runtime, top_recommendation)
            logger.info("node_finished", node=NODE_NAME, available=False)
            return result

        result = await _build_available_response(state, runtime, top_recommendation)
        logger.info("node_finished", node=NODE_NAME, available=True)
        return result
    except Exception:
        logger.error("generate_output_unexpected_failure", exc_info=True)
        return {
            "final_response": top_recommendation.get("explanation")
            or top_recommendation.get("overall_summary")
            or "A recommendation was reached, but building the full response failed unexpectedly.",
            "stream_messages": [f"[{NODE_NAME}] Failed unexpectedly — showing a partial response."],
        }
