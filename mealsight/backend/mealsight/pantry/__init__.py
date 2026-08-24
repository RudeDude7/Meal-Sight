"""The Pantry Manager — plain Python tools over the local pantry table:
merging reported items, reading them back with freshness/expiry info,
and removing consumed quantities. All deterministic, no LLM calls
anywhere. No MCP wrapper yet — these are called directly for now.
"""

from mealsight.pantry.models import (
    FlaggedPantryItem,
    FreshnessFilter,
    PantryChangeDetail,
    PantryItem,
    PantryItemInput,
    PantryUpdateResult,
    RemovalDetail,
    RemovalItemInput,
    RemovalResult,
)
from mealsight.pantry.query import get_pantry
from mealsight.pantry.remove import remove_items
from mealsight.pantry.shelf_life import CATEGORY_DEFAULTS, ShelfLifeEntry, resolve_shelf_life
from mealsight.pantry.update import update_pantry

__all__ = [
    "CATEGORY_DEFAULTS",
    "FlaggedPantryItem",
    "FreshnessFilter",
    "PantryChangeDetail",
    "PantryItem",
    "PantryItemInput",
    "PantryUpdateResult",
    "RemovalDetail",
    "RemovalItemInput",
    "RemovalResult",
    "ShelfLifeEntry",
    "get_pantry",
    "remove_items",
    "resolve_shelf_life",
    "update_pantry",
]
