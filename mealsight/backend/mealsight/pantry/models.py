"""Typed input/result shapes for the Pantry Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mealsight.matching.models import Importance

FreshnessFilter = Literal["expiring_soon", "fresh", "all"]

GrocerySection = Literal["produce", "protein", "dairy", "bakery", "pantry", "frozen", "spices", "other"]


class PantryItemInput(BaseModel):
    """One item as reported by a caller (typically vision analysis) —
    the input shape for update_pantry."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None
    unit: str | None
    category: str
    freshness_status: str = "fresh"


class PantryItem(BaseModel):
    """One row of the pantry table, as returned by get_pantry.
    days_remaining is computed from estimated_shelf_days and added_date —
    None when estimated_shelf_days itself is unknown."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    quantity: float | None
    unit: str | None
    category: str
    freshness_status: str
    estimated_shelf_days: int | None
    days_remaining: int | None
    added_date: datetime
    last_seen_date: datetime
    source: str


class PantryChangeDetail(BaseModel):
    """What update_pantry did with one input item."""

    model_config = ConfigDict(frozen=True)

    name: str
    canonical_name: str
    action: Literal["added", "updated"]
    quantity_after: float | None


class FlaggedPantryItem(BaseModel):
    """A pre-existing pantry item whose last_seen_date is older than
    settings.stale_pantry_item_days — not necessarily part of the batch
    that triggered this flag, since a stale item is by definition one
    that hasn't been reported in a while."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    last_seen_date: datetime
    days_since_seen: int


class PantryUpdateResult(BaseModel):
    """What update_pantry returns: counts plus per-item and per-flag
    detail, so a caller can both summarize ("added 3, updated 2") and
    inspect exactly what happened to any specific item."""

    model_config = ConfigDict(frozen=True)

    added_count: int
    updated_count: int
    flagged_count: int
    details: list[PantryChangeDetail]
    flagged_items: list[FlaggedPantryItem]


class RemovalItemInput(BaseModel):
    """One item to remove from the pantry — from cooking a recipe,
    throwing something out, or any other consumption."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity_used: float
    used_for_recipe: str | None = None


class RemovalDetail(BaseModel):
    """What remove_items did with one requested removal.
    quantity_removed is always <= what was actually present — over-
    removal is clamped, never driven negative — and discrepancy reports
    exactly how much of the request that clamp had to drop, so a caller
    can tell "assumed to be all gone" apart from "removed exactly what
    was asked."""

    model_config = ConfigDict(frozen=True)

    name: str
    canonical_name: str
    found: bool
    quantity_requested: float
    quantity_removed: float
    quantity_remaining: float
    discrepancy: float
    deleted: bool


class RemovalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    details: list[RemovalDetail]


class ExpiringItem(BaseModel):
    """One pantry item flagged by flag_expiring — already sorted by
    urgency (most negative days_remaining, i.e. most overdue, first) by
    the time a caller sees a list of these."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None
    unit: str | None
    days_remaining: int
    suggested_action: str


class MissingIngredientInput(BaseModel):
    """One ingredient one recipe is missing — the shape
    create_grocery_list expects nested under RecipeMissingIngredients.
    Deliberately not mealsight.matching.models.MissingItem: that type
    only carries name and importance (match_ingredients has no reason to
    know quantity/unit), so a caller assembling this input has to look
    quantity/unit back up from the recipe itself (e.g. via
    mealsight.recipe_engine.get_recipe) — that join is the caller's job,
    not this module's."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None
    unit: str | None
    importance: Importance


class RecipeMissingIngredients(BaseModel):
    """One recipe's contribution to a grocery list — the top-level input
    shape for create_grocery_list."""

    model_config = ConfigDict(frozen=True)

    recipe_id: str
    recipe_name: str
    missing_ingredients: list[MissingIngredientInput]


class GroceryQuantity(BaseModel):
    """One (quantity, unit) pair on a grocery list line. A line has more
    than one of these only when the same ingredient was needed in
    different, non-combinable units across recipes."""

    model_config = ConfigDict(frozen=True)

    quantity: float | None
    unit: str | None


class GroceryListItem(BaseModel):
    """One line on a grocery list: one canonical ingredient, aggregated
    across every recipe that needs it."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantities: list[GroceryQuantity]
    needed_for: list[str]
    importance: Importance
    section: GrocerySection
    is_staple: bool
    verify_note: str | None
    checked: bool = False


class GroceryListSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: GrocerySection
    items: list[GroceryListItem]


class GroceryList(BaseModel):
    """A full grocery list, as returned by create_grocery_list and
    get_grocery_list. Section order is always the fixed order in
    mealsight.pantry.grocery.SECTION_ORDER, and only sections with at
    least one item are included."""

    model_config = ConfigDict(frozen=True)

    id: int
    status: str
    created_at: datetime
    sections: list[GroceryListSection]
