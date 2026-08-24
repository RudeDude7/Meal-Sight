"""Typed input/result shapes for the Pantry Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FreshnessFilter = Literal["expiring_soon", "fresh", "all"]


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
