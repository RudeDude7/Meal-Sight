"""update_pantry — merges a batch of reported items (typically from
vision analysis) into the pantry table.

Deterministic, no LLM calls. Every item name is resolved through the
exact same normalizer and synonym table the ingredient matcher uses
(mealsight.matching), so "scallions" and "green onion" — or "Chopped
tomatoes" and "tomato" — merge into the same pantry row rather than
becoming two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry._datetime_utils import parse_sqlite_timestamp
from mealsight.pantry.models import FlaggedPantryItem, PantryChangeDetail, PantryItemInput, PantryUpdateResult
from mealsight.pantry.shelf_life import load_shelf_life_map, resolve_shelf_life


async def _find_stale_items(pantry_db: Database) -> list[FlaggedPantryItem]:
    """Scans every current pantry row (not just this batch — a stale
    item is by definition one that wasn't just re-confirmed) and flags
    any whose last_seen_date is older than settings.stale_pantry_item_days."""
    rows = await pantry_db.fetch_all("SELECT id, name, last_seen_date FROM pantry")
    now = datetime.utcnow()

    flagged: list[FlaggedPantryItem] = []
    for row in rows:
        last_seen = parse_sqlite_timestamp(row["last_seen_date"])
        days_since_seen = (now - last_seen).days
        if days_since_seen > settings.stale_pantry_item_days:
            flagged.append(
                FlaggedPantryItem(
                    id=row["id"], name=row["name"], last_seen_date=last_seen, days_since_seen=days_since_seen
                )
            )
    return flagged


async def update_pantry(
    items: Sequence[PantryItemInput],
    pantry_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> PantryUpdateResult:
    """Merges items into the pantry table.

    An item whose canonical name matches an existing row has its
    quantity ADDED to what's already there (never replaced), and its
    freshness_status and last_seen_date refreshed. An item with no
    match is inserted fresh, with estimated_shelf_days assigned by
    mealsight.pantry.shelf_life.resolve_shelf_life. Existing pantry rows
    absent from this batch are left completely untouched — never
    deleted — since a real pantry has cabinets and drawers no single
    photo sees.

    synonym_map defaults to loading from the real recipes.db (where
    ingredient_synonyms actually lives — it's a recipes.db table, not a
    pantry.db one) if not supplied; pass one directly to test against a
    hand-built map without a second real database.
    """
    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())
    shelf_life_map = await load_shelf_life_map(pantry_db)

    details: list[PantryChangeDetail] = []
    added_count = 0
    updated_count = 0

    for item in items:
        canonical = resolve_canonical(normalize_ingredient(item.name), synonym_map)
        existing = await pantry_db.fetch_one("SELECT id, quantity FROM pantry WHERE name = ?", (canonical,))

        if existing is not None:
            new_quantity = (existing["quantity"] or 0.0) + (item.quantity or 0.0)
            await pantry_db.execute(
                "UPDATE pantry SET quantity = ?, freshness_status = ?, last_seen_date = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (new_quantity, item.freshness_status, existing["id"]),
            )
            updated_count += 1
            details.append(
                PantryChangeDetail(
                    name=item.name, canonical_name=canonical, action="updated", quantity_after=new_quantity
                )
            )
        else:
            shelf_days = resolve_shelf_life(canonical, item.category, shelf_life_map)
            await pantry_db.execute(
                """
                INSERT INTO pantry (
                    name, quantity, unit, category, freshness_status,
                    estimated_shelf_days, added_date, last_seen_date, source
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'photo')
                """,
                (canonical, item.quantity, item.unit, item.category, item.freshness_status, shelf_days),
            )
            added_count += 1
            details.append(
                PantryChangeDetail(
                    name=item.name, canonical_name=canonical, action="added", quantity_after=item.quantity
                )
            )

    flagged_items = await _find_stale_items(pantry_db)

    return PantryUpdateResult(
        added_count=added_count,
        updated_count=updated_count,
        flagged_count=len(flagged_items),
        details=details,
        flagged_items=flagged_items,
    )
