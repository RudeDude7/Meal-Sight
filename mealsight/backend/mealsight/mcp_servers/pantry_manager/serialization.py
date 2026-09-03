"""Converts mealsight.pantry pydantic result models into plain,
JSON-serializable dicts with a stable shape — what the pantry-manager
MCP tools actually return — plus the structured error shapes every tool
returns instead of letting an exception escape.
"""

from __future__ import annotations

from typing import Any

from mealsight.mcp_servers.errors import internal_error, not_found_error, validation_error
from mealsight.pantry.models import (
    ExpiringItem,
    GroceryList,
    PantryItem,
    PantryUpdateResult,
    RemovalResult,
    WasteLogResult,
    WasteStats,
)

__all__ = [
    "expiring_items_to_dict",
    "grocery_list_to_dict",
    "internal_error",
    "not_found_error",
    "pantry_items_to_dict",
    "pantry_update_result_to_dict",
    "removal_result_to_dict",
    "validation_error",
    "waste_log_result_to_dict",
    "waste_stats_to_dict",
]


def pantry_update_result_to_dict(result: PantryUpdateResult) -> dict[str, Any]:
    """Shape: {"added_count", "updated_count", "flagged_count",
    "details": [{"name", "canonical_name", "action", "quantity_after"}, ...],
    "flagged_items": [{"id", "name", "last_seen_date", "days_since_seen"}, ...]}.
    flagged_items are pre-existing pantry rows that have gone stale — not
    necessarily anything in this batch."""
    return result.model_dump(mode="json")


def pantry_items_to_dict(items: list[PantryItem]) -> dict[str, Any]:
    """Shape: {"items": [{"id", "name", "quantity", "unit", "category",
    "freshness_status", "estimated_shelf_days", "days_remaining",
    "added_date", "last_seen_date", "source"}, ...], "count": int}."""
    return {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}


def removal_result_to_dict(result: RemovalResult) -> dict[str, Any]:
    """Shape: {"details": [{"name", "canonical_name", "found",
    "quantity_requested", "quantity_removed", "quantity_remaining",
    "discrepancy", "deleted"}, ...]}. discrepancy is how much of the
    request could not actually be removed (0 when the full amount was
    on hand)."""
    return result.model_dump(mode="json")


def expiring_items_to_dict(items: list[ExpiringItem]) -> dict[str, Any]:
    """Shape: {"items": [{"name", "quantity", "unit", "days_remaining",
    "suggested_action"}, ...], "count": int}. Already sorted most-urgent
    first (most negative days_remaining, i.e. already expired, sorts
    ahead of anything still counting down)."""
    return {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}


def waste_log_result_to_dict(result: WasteLogResult) -> dict[str, Any]:
    """Shape: {"id", "item_name", "canonical_name", "quantity_wasted",
    "unit", "reason", "logged_at", "removal": {...same shape as
    remove_items' own detail...}, "insight"}. insight is null unless
    this item has now been logged as wasted settings.waste_insight_
    threshold times or more, all-time."""
    return result.model_dump(mode="json")


def waste_stats_to_dict(stats: WasteStats) -> dict[str, Any]:
    """Shape: {"time_range", "total_items_wasted", "most_wasted":
    [{"item_name", "count", "dominant_reason"}, ...], "trend": {
    "current_period_count", "previous_period_count", "change_pct",
    "message"}, "active_insights": [str, ...]}. change_pct is null
    (with an explanatory message) whenever either period has too few
    entries to compare meaningfully, or for time_range="all_time".
    active_insights is always computed all-time, independent of
    time_range."""
    return stats.model_dump(mode="json")


def grocery_list_to_dict(grocery_list: GroceryList) -> dict[str, Any]:
    """Shape: {"id", "status", "created_at", "sections": [{"section",
    "items": [{"name", "quantities": [{"quantity", "unit"}, ...],
    "needed_for", "importance", "section", "is_staple", "verify_note",
    "checked"}, ...]}, ...]}. Only sections with at least one item are
    present, in the fixed store-aisle order (produce, protein, dairy,
    bakery, pantry, frozen, spices, other)."""
    return grocery_list.model_dump(mode="json")
