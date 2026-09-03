"""The pantry-manager MCP server: a thin FastMCP transport shell over
mealsight.pantry. Every tool here validates its own input, calls
straight into an existing, independently-tested function, and
serializes the result (mealsight.mcp_servers.pantry_manager.
serialization) — no pantry, expiry, or grocery-list logic is
reimplemented in this file. If a rule about what "expiring soon" or
"which store section" means ever needs to change, it changes in the
underlying module, not here.

Deterministic, no LLM calls anywhere in this module either.
"""

from __future__ import annotations

from typing import Any, get_args

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict

from mealsight.db import get_pantry_db
from mealsight.mcp_servers.pantry_manager.serialization import (
    expiring_items_to_dict,
    grocery_list_to_dict,
    internal_error,
    not_found_error,
    pantry_items_to_dict,
    pantry_update_result_to_dict,
    removal_result_to_dict,
    validation_error,
    waste_log_result_to_dict,
    waste_stats_to_dict,
)
from mealsight.pantry import create_grocery_list as _create_grocery_list
from mealsight.pantry import flag_expiring as _flag_expiring
from mealsight.pantry import get_grocery_list as _get_grocery_list
from mealsight.pantry import get_pantry as _get_pantry
from mealsight.pantry import get_waste_stats as _get_waste_stats
from mealsight.pantry import log_waste as _log_waste
from mealsight.pantry import remove_items as _remove_items
from mealsight.pantry import update_pantry as _update_pantry
from mealsight.pantry.models import (
    FreshnessFilter,
    PantryItemInput,
    RecipeMissingIngredients,
    RemovalItemInput,
    WasteReason,
    WasteTimeRange,
)
from mealsight.pantry.waste import InvalidWasteReasonError
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.pantry_manager")

mcp: FastMCP[Any] = FastMCP("pantry-manager")

_FRESHNESS_FILTERS: tuple[str, ...] = get_args(FreshnessFilter)
_WASTE_REASONS: tuple[str, ...] = get_args(WasteReason)
_WASTE_TIME_RANGES: tuple[str, ...] = get_args(WasteTimeRange)


class RemovalItem(BaseModel):
    """One item to remove from the pantry — the input shape for
    remove_items. used_for_recipe is not part of this shape: remove_items
    takes a single recipe_name that applies to the whole batch instead."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity_used: float


@mcp.tool
async def update_pantry(items: list[PantryItemInput]) -> dict[str, Any]:
    """Records what's currently in the pantry — typically the output of
    a vision analysis pass over a fridge/pantry photo, but any source of
    "here's what's on hand right now" works.

    IMPORTANT: this ADDS to existing quantities rather than replacing
    them, and it NEVER deletes a pantry row just because that item is
    absent from this batch — a single photo only ever sees part of a
    real kitchen, so an item matched by canonical name to an existing
    row gets its quantity increased and its freshness/last-seen data
    refreshed, while a genuinely new item is inserted fresh with an
    estimated shelf life. To decrease or remove pantry quantities (e.g.
    after cooking), use remove_items instead — never call update_pantry
    with a smaller quantity expecting it to subtract.

    Each item needs name, quantity, unit, category, and optionally
    freshness_status (defaults to "fresh").

    Returns {"added_count", "updated_count", "flagged_count", "details":
    [{"name", "canonical_name", "action": "added"|"updated",
    "quantity_after"}, ...], "flagged_items": [...]}. flagged_items lists
    pre-existing pantry rows that haven't been seen in a while (stale),
    regardless of whether this batch touched them — worth surfacing to
    a user even when this update didn't mention them at all.
    """
    try:
        db = get_pantry_db()
        result = await _update_pantry(items, pantry_db=db)
        return pantry_update_result_to_dict(result)
    except Exception:
        logger.error("update_pantry_failed", exc_info=True, item_count=len(items))
        return internal_error()


@mcp.tool
async def get_pantry(
    category: str | None = None,
    freshness_filter: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Reads back what's currently believed to be in the pantry, with
    days_remaining computed per item. Use this to answer "what do I
    have" or "do I have X" questions, or before deciding what a recipe
    is still missing.

    freshness_filter (omit for no freshness filtering at all):
        "fresh" — only items whose stored freshness_status is "fresh".
        "expiring_soon" — only items at or below the configured
        expiring-soon threshold, including items already past their
        estimated shelf life. Prefer flag_expiring over this option when
        the goal is specifically "what needs to be used up soon" — it
        also sorts by urgency and adds a suggested_action per item.
        "all" — equivalent to omitting the filter.

    search matches as a case-insensitive substring against each item's
    canonical (normalized) name.

    Returns {"items": [{"id", "name", "quantity", "unit", "category",
    "freshness_status", "estimated_shelf_days", "days_remaining",
    "added_date", "last_seen_date", "source"}, ...], "count": int}.
    days_remaining is null when estimated_shelf_days itself is unknown.

    Returns a structured {"error": "validation_error", ...} naming the
    accepted freshness_filter values if it isn't one of them.
    """
    if freshness_filter is not None and freshness_filter not in _FRESHNESS_FILTERS:
        return validation_error(
            "freshness_filter",
            f"{freshness_filter!r} is not a recognized freshness_filter.",
            accepted=list(_FRESHNESS_FILTERS),
        )
    try:
        db = get_pantry_db()
        items = await _get_pantry(
            category=category,
            freshness_filter=freshness_filter or "all",  # type: ignore[arg-type]
            search=search,
            pantry_db=db,
        )
        return pantry_items_to_dict(items)
    except Exception:
        logger.error("get_pantry_failed", exc_info=True, category=category, search=search)
        return internal_error()


@mcp.tool
async def remove_items(items: list[RemovalItem], recipe_name: str | None = None) -> dict[str, Any]:
    """Decrements pantry quantities for items actually consumed.

    IMPORTANT: call this AFTER cooking has actually been confirmed as
    having happened — not when a recipe is merely recommended or
    planned. Calling this for a recipe that hasn't actually been cooked
    yet will incorrectly empty the pantry.

    recipe_name (optional) is recorded against every item in this batch
    in the consumption log, for later history/analytics — pass the
    recipe that was cooked, or omit it for a removal not tied to any one
    recipe (e.g. throwing out spoiled food).

    Removing more than is actually on hand clamps at zero rather than
    going negative: quantity_removed is capped at what was really there,
    and discrepancy reports how much of the request that clamp had to
    drop (0 when the full amount was available). A row that reaches
    zero is deleted outright.

    Returns {"details": [{"name", "canonical_name", "found",
    "quantity_requested", "quantity_removed", "quantity_remaining",
    "discrepancy", "deleted"}, ...]}. An item not found in the pantry at
    all is reported with found=false rather than raising.
    """
    try:
        db = get_pantry_db()
        removal_inputs = [
            RemovalItemInput(name=item.name, quantity_used=item.quantity_used, used_for_recipe=recipe_name)
            for item in items
        ]
        result = await _remove_items(removal_inputs, pantry_db=db)
        return removal_result_to_dict(result)
    except Exception:
        logger.error("remove_items_failed", exc_info=True, item_count=len(items))
        return internal_error()


@mcp.tool
async def flag_expiring(days_threshold: int | None = None) -> dict[str, Any]:
    """Returns pantry items that need attention soon, sorted by urgency
    (already-expired items first), each with a suggested_action ("use
    today", "freeze to extend", "already expired — verify and discard if
    spoiled", or "use within N days"). Use this over get_pantry's
    "expiring_soon" filter whenever the goal is specifically "what
    should I use up" — this tool also sorts by urgency and explains what
    to do about each item, which get_pantry does not.

    days_threshold (omit to use the configured default) is the cutoff in
    days: an item is included when its days_remaining is known and at or
    below this value. An item with unknown estimated shelf life is never
    included, since there's nothing to compare.

    Returns {"items": [{"name", "quantity", "unit", "days_remaining",
    "suggested_action"}, ...], "count": int}. An empty pantry (or none
    of it meeting the threshold) returns an empty list, not an error.

    Returns a structured {"error": "validation_error", ...} naming
    days_threshold if it isn't a positive integer.
    """
    if days_threshold is not None and days_threshold <= 0:
        return validation_error(
            "days_threshold",
            f"days_threshold must be a positive integer, got {days_threshold}.",
        )
    try:
        db = get_pantry_db()
        items = await _flag_expiring(days_threshold=days_threshold, pantry_db=db)
        return expiring_items_to_dict(items)
    except Exception:
        logger.error("flag_expiring_failed", exc_info=True, days_threshold=days_threshold)
        return internal_error()


@mcp.tool
async def create_grocery_list(missing_by_recipe: list[RecipeMissingIngredients]) -> dict[str, Any]:
    """Builds one deduplicated, store-organized grocery list from every
    recipe's missing ingredients, and persists it as the new active
    list. Call this after match_ingredients (from the recipe-engine
    server) has identified what one or more recipes are missing.

    missing_by_recipe is a list, one entry per recipe, each shaped as:
        {
          "recipe_id": "abc123",
          "recipe_name": "Chicken Stir Fry",
          "missing_ingredients": [
            {"name": "soy sauce", "quantity": 2, "unit": "tbsp", "importance": "critical"},
            {"name": "garlic", "quantity": null, "unit": null, "importance": "optional"}
          ]
        }
    quantity/unit may be null when unknown; importance is one of
    "critical", "important", "optional". Include an entry per recipe
    that has any missing ingredients — the same ingredient appearing
    under multiple recipes is automatically combined into one line.

    Returns {"id", "status", "created_at", "sections": [{"section",
    "items": [{"name", "quantities": [{"quantity", "unit"}, ...],
    "needed_for": [recipe names], "importance", "section", "is_staple",
    "verify_note", "checked"}, ...]}, ...]}. is_staple/verify_note flag
    common items (salt, oil, flour, ...) a kitchen usually already has —
    these still appear on the list to verify, not silently dropped.
    Quantities only combine when their units match; mismatched units
    (e.g. 2 cloves vs. 1 head) stay as separate entries on the same
    line rather than being guessed at.
    """
    try:
        db = get_pantry_db()
        result = await _create_grocery_list(missing_by_recipe, pantry_db=db)
        return grocery_list_to_dict(result)
    except Exception:
        logger.error("create_grocery_list_failed", exc_info=True, recipe_count=len(missing_by_recipe))
        return internal_error()


@mcp.tool
async def get_grocery_list(list_id: int | None = None) -> dict[str, Any]:
    """Fetches one grocery list. Omit list_id to get the most recently
    created active list — use this form for "what's on my grocery list"
    style questions. Pass a specific list_id to fetch a particular past
    list.

    Returns the same shape as create_grocery_list: {"id", "status",
    "created_at", "sections": [...]}.

    Returns a structured {"error": "not_found", ...} result, not an
    exception, if list_id doesn't match any list, or if list_id is
    omitted and no active list currently exists.
    """
    try:
        db = get_pantry_db()
        result = await _get_grocery_list(list_id=list_id, pantry_db=db)
        if result is None:
            list_ref = str(list_id) if list_id is not None else "(most recent active)"
            return not_found_error("grocery_list", list_ref)
        return grocery_list_to_dict(result)
    except Exception:
        logger.error("get_grocery_list_failed", exc_info=True, list_id=list_id)
        return internal_error()


@mcp.tool
async def log_waste(
    item_name: str, quantity_wasted: float, unit: str | None, reason: str
) -> dict[str, Any]:
    """Logs one instance of item_name being thrown out and DEDUCTS
    quantity_wasted from the pantry in the same call — a user throwing
    something out has already lost it, so there is no separate "now
    remove it" step; this tool already calls remove_items internally
    (the exact same clamped-removal logic, writing the same
    consumption_log entry any other removal would).

    reason must be one of "expired", "spoiled", "didn_t_like",
    "too_much".

    Once this item has been logged as wasted settings.waste_insight_
    threshold times or more (all-time, not just recently), the result's
    own "insight" field carries a specific, data-derived sentence
    naming the item, the count, and the dominant reason (e.g. "You've
    thrown away spinach 4 times, all expired — consider buying smaller
    amounts or keeping extra in the freezer.") — null until that
    threshold is actually reached.

    Returns {"id", "item_name", "canonical_name", "quantity_wasted",
    "unit", "reason", "logged_at", "removal": {"name", "canonical_name",
    "found", "quantity_requested", "quantity_removed",
    "quantity_remaining", "discrepancy", "deleted"}, "insight"}.

    Returns a structured {"error": "validation_error", ...} naming the
    accepted reason values if reason isn't one of them.
    """
    if reason not in _WASTE_REASONS:
        return validation_error(
            "reason", f"{reason!r} is not a recognized waste reason.", accepted=list(_WASTE_REASONS)
        )
    try:
        db = get_pantry_db()
        result = await _log_waste(item_name, quantity_wasted, unit, reason, pantry_db=db)
        return waste_log_result_to_dict(result)
    except InvalidWasteReasonError:
        # Defensive: _WASTE_REASONS is derived from the exact same
        # WasteReason Literal log_waste itself validates against, so
        # this should be unreachable given the check above — kept as a
        # real translated error rather than an uncaught 500 in case the
        # two ever drift.
        return validation_error(
            "reason", f"{reason!r} is not a recognized waste reason.", accepted=list(_WASTE_REASONS)
        )
    except Exception:
        logger.error("log_waste_failed", exc_info=True, item_name=item_name)
        return internal_error()


@mcp.tool
async def get_waste_stats(time_range: str) -> dict[str, Any]:
    """Returns waste statistics for time_range ("this_week",
    "this_month", or "all_time"): total_items_wasted (a count of
    logged waste events in the window, not a quantity sum — quantities
    can be in incompatible units), most_wasted (ranked by count within
    the window, each with its dominant reason), trend (the window's
    count against the immediately preceding equivalent period — null
    change_pct with an explanatory message when either period has too
    few entries to compare meaningfully, or for "all_time", which has
    no previous period at all), and active_insights (every item
    currently at or above the insight threshold, ALWAYS computed
    all-time regardless of time_range — an insight is a standing
    behavioral flag, not something that resets just because a narrower
    window was requested).

    Returns a structured {"error": "validation_error", ...} naming the
    accepted time_range values if it isn't one of them.
    """
    if time_range not in _WASTE_TIME_RANGES:
        return validation_error(
            "time_range",
            f"{time_range!r} is not a recognized time_range.",
            accepted=list(_WASTE_TIME_RANGES),
        )
    try:
        db = get_pantry_db()
        result = await _get_waste_stats(time_range, pantry_db=db)  # type: ignore[arg-type]
        return waste_stats_to_dict(result)
    except Exception:
        logger.error("get_waste_stats_failed", exc_info=True, time_range=time_range)
        return internal_error()
