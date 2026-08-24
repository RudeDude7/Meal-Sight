"""Resolves a pantry item's estimated shelf life in days, from
shelf_life_reference when an exact row exists, falling back to a
category-level default otherwise — so an item the reference data has
never heard of still gets a sane, non-null estimated_shelf_days rather
than silently going untracked.

Load-once, in-memory cache, the same shape mealsight.matching.synonyms
and mealsight.matching.substitutions already use for their own reference
tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mealsight.db.connection import Database

_shelf_life_cache: dict[str, ShelfLifeEntry] | None = None


@dataclass(frozen=True)
class ShelfLifeEntry:
    category: str
    shelf_days_refrigerated: int | None
    shelf_days_frozen: int | None
    shelf_days_pantry: int | None


# Used only when an item has no exact shelf_life_reference row at all.
# Deliberately conservative (shorter rather than longer) where a category
# spans a wide range of real shelf lives, since underestimating just
# means an item gets flagged for a look sooner than strictly necessary,
# while overestimating risks it going unnoticed after actually spoiling.
CATEGORY_DEFAULTS: dict[str, ShelfLifeEntry] = {
    "protein": ShelfLifeEntry(
        "protein", shelf_days_refrigerated=2, shelf_days_frozen=180, shelf_days_pantry=None
    ),
    "vegetable": ShelfLifeEntry(
        "vegetable", shelf_days_refrigerated=7, shelf_days_frozen=240, shelf_days_pantry=None
    ),
    "fruit": ShelfLifeEntry("fruit", shelf_days_refrigerated=7, shelf_days_frozen=240, shelf_days_pantry=7),
    "dairy": ShelfLifeEntry(
        "dairy", shelf_days_refrigerated=10, shelf_days_frozen=60, shelf_days_pantry=None
    ),
    "grain": ShelfLifeEntry(
        "grain", shelf_days_refrigerated=None, shelf_days_frozen=None, shelf_days_pantry=365
    ),
    "condiment": ShelfLifeEntry(
        "condiment", shelf_days_refrigerated=90, shelf_days_frozen=None, shelf_days_pantry=365
    ),
}

# The last resort: a category this codebase has never heard of at all
# (not even one of CATEGORY_DEFAULTS' six keys). Short and refrigerated,
# the safest assumption when nothing else is known.
_UNKNOWN_CATEGORY_DEFAULT = ShelfLifeEntry(
    "unknown", shelf_days_refrigerated=7, shelf_days_frozen=None, shelf_days_pantry=None
)


async def load_shelf_life_map(db: Database) -> dict[str, ShelfLifeEntry]:
    """Loads every shelf_life_reference row into a dict of item_name (the
    table's own normalized primary key, per mealsight.seed.load_shelf_life)
    -> ShelfLifeEntry, caching the result in-process."""
    global _shelf_life_cache
    if _shelf_life_cache is not None:
        return _shelf_life_cache

    rows = await db.fetch_all(
        "SELECT item_name, category, shelf_days_refrigerated, shelf_days_frozen, shelf_days_pantry "
        "FROM shelf_life_reference"
    )
    mapping: dict[str, ShelfLifeEntry] = {
        row["item_name"]: ShelfLifeEntry(
            category=row["category"],
            shelf_days_refrigerated=row["shelf_days_refrigerated"],
            shelf_days_frozen=row["shelf_days_frozen"],
            shelf_days_pantry=row["shelf_days_pantry"],
        )
        for row in rows
    }
    _shelf_life_cache = mapping
    return mapping


def reset_shelf_life_cache() -> None:
    """Clears the in-memory cache. Exists for tests; application code
    has no reason to call this, since shelf_life_reference doesn't
    change at runtime."""
    global _shelf_life_cache
    _shelf_life_cache = None


def resolve_shelf_life(
    canonical_item_name: str, category: str, shelf_life_map: Mapping[str, ShelfLifeEntry]
) -> int:
    """Returns a single estimated-shelf-life-in-days number for one
    pantry item: the exact shelf_life_reference row if one exists for
    canonical_item_name, otherwise CATEGORY_DEFAULTS[category] (or the
    unknown-category default if category itself isn't recognized
    either).

    A shelf_life_reference / category-default row carries three separate
    numbers (refrigerated/frozen/pantry storage), but pantry.
    estimated_shelf_days is a single column — this picks refrigerated
    first (the assumption for a freshly-photographed item that hasn't
    been told otherwise), then pantry, then frozen last (frozen storage
    is an active choice a user made, not a default to assume), falling
    back to a flat week if a category default somehow has all three as
    null.
    """
    entry = shelf_life_map.get(canonical_item_name) or CATEGORY_DEFAULTS.get(
        category.lower(), _UNKNOWN_CATEGORY_DEFAULT
    )
    for value in (entry.shelf_days_refrigerated, entry.shelf_days_pantry, entry.shelf_days_frozen):
        if value is not None:
            return value
    return 7
