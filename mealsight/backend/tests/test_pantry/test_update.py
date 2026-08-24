"""Tests for mealsight.pantry.update.update_pantry."""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.pantry.models import PantryItemInput
from mealsight.pantry.update import update_pantry

_SYNONYMS = {"scallion": "green onion"}


def _item(name: str, quantity: float, category: str = "vegetable", unit: str = "count") -> PantryItemInput:
    return PantryItemInput(name=name, quantity=quantity, unit=unit, category=category)


async def test_quantity_accumulates_rather_than_replaces(pantry_db: Database) -> None:
    await update_pantry([_item("onion", 2.0)], pantry_db=pantry_db, synonym_map={})
    result = await update_pantry([_item("onion", 3.0)], pantry_db=pantry_db, synonym_map={})

    row = await pantry_db.fetch_one("SELECT quantity FROM pantry WHERE name = 'onion'")
    assert row is not None
    assert row["quantity"] == 5.0
    assert result.updated_count == 1
    assert result.added_count == 0


async def test_synonym_differing_names_merge_into_one_row(pantry_db: Database) -> None:
    await update_pantry([_item("scallions", 1.0)], pantry_db=pantry_db, synonym_map=_SYNONYMS)
    result = await update_pantry([_item("green onion", 1.0)], pantry_db=pantry_db, synonym_map=_SYNONYMS)

    rows = await pantry_db.fetch_all("SELECT name, quantity FROM pantry")
    assert len(rows) == 1
    assert rows[0]["name"] == "green onion"
    assert rows[0]["quantity"] == 2.0
    assert result.updated_count == 1
    assert result.added_count == 0


async def test_absent_items_survive_a_merge(pantry_db: Database) -> None:
    await update_pantry([_item("onion", 1.0), _item("garlic", 1.0)], pantry_db=pantry_db, synonym_map={})

    # A second batch mentions only onion — garlic must not be touched or removed.
    await update_pantry([_item("onion", 1.0)], pantry_db=pantry_db, synonym_map={})

    rows = await pantry_db.fetch_all("SELECT name FROM pantry")
    names = {row["name"] for row in rows}
    assert names == {"onion", "garlic"}


async def test_new_item_is_inserted_with_a_resolved_shelf_life(pantry_db: Database) -> None:
    result = await update_pantry([_item("carrot", 5.0)], pantry_db=pantry_db, synonym_map={})

    row = await pantry_db.fetch_one("SELECT estimated_shelf_days FROM pantry WHERE name = 'carrot'")
    assert row is not None
    assert row["estimated_shelf_days"] is not None
    assert result.added_count == 1
    assert result.details[0].action == "added"


async def test_stale_flagging_fires_at_the_configured_threshold(pantry_db: Database) -> None:
    await update_pantry([_item("garlic", 1.0)], pantry_db=pantry_db, synonym_map={})

    # Back-date last_seen_date past the stale threshold directly.
    stale_days = settings.stale_pantry_item_days + 1
    await pantry_db.execute(
        f"UPDATE pantry SET last_seen_date = datetime('now', '-{stale_days} days') WHERE name = 'garlic'"
    )

    # Any subsequent update_pantry call re-scans the whole pantry for staleness.
    result = await update_pantry([_item("onion", 1.0)], pantry_db=pantry_db, synonym_map={})

    flagged_names = {item.name for item in result.flagged_items}
    assert "garlic" in flagged_names
    assert "onion" not in flagged_names  # just touched — definitely not stale
    assert result.flagged_count == len(result.flagged_items)


async def test_item_just_updated_is_never_flagged_stale_even_if_it_was_before(pantry_db: Database) -> None:
    await update_pantry([_item("garlic", 1.0)], pantry_db=pantry_db, synonym_map={})
    stale_days = settings.stale_pantry_item_days + 1
    await pantry_db.execute(
        f"UPDATE pantry SET last_seen_date = datetime('now', '-{stale_days} days') WHERE name = 'garlic'"
    )

    # Re-report garlic itself in this batch — its last_seen_date gets refreshed.
    result = await update_pantry([_item("garlic", 1.0)], pantry_db=pantry_db, synonym_map={})

    flagged_names = {item.name for item in result.flagged_items}
    assert "garlic" not in flagged_names
