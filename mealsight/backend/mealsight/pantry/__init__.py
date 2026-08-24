"""The Pantry Manager — plain Python tools over the local pantry table:
merging reported items, reading them back with freshness/expiry info,
removing consumed quantities, flagging what's about to go bad, and
building/reading grocery lists. All deterministic, no LLM calls
anywhere. No MCP wrapper yet — these are called directly for now.
"""

from mealsight.pantry.category import EXPLICIT_CATEGORY_MAP, Category, resolve_category
from mealsight.pantry.expiring import flag_expiring
from mealsight.pantry.grocery import (
    CATEGORY_TO_SECTION,
    SECTION_ORDER,
    STAPLE_ITEMS,
    create_grocery_list,
    get_grocery_list,
    set_grocery_item_checked,
)
from mealsight.pantry.models import (
    ExpiringItem,
    FlaggedPantryItem,
    FreshnessFilter,
    GroceryList,
    GroceryListItem,
    GroceryListSection,
    GroceryQuantity,
    GrocerySection,
    MissingIngredientInput,
    PantryChangeDetail,
    PantryItem,
    PantryItemInput,
    PantryUpdateResult,
    RecipeMissingIngredients,
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
    "CATEGORY_TO_SECTION",
    "EXPLICIT_CATEGORY_MAP",
    "SECTION_ORDER",
    "STAPLE_ITEMS",
    "Category",
    "ExpiringItem",
    "FlaggedPantryItem",
    "FreshnessFilter",
    "GroceryList",
    "GroceryListItem",
    "GroceryListSection",
    "GroceryQuantity",
    "GrocerySection",
    "MissingIngredientInput",
    "PantryChangeDetail",
    "PantryItem",
    "PantryItemInput",
    "PantryUpdateResult",
    "RecipeMissingIngredients",
    "RemovalDetail",
    "RemovalItemInput",
    "RemovalResult",
    "ShelfLifeEntry",
    "create_grocery_list",
    "flag_expiring",
    "get_grocery_list",
    "get_pantry",
    "remove_items",
    "resolve_category",
    "resolve_shelf_life",
    "set_grocery_item_checked",
    "update_pantry",
]
