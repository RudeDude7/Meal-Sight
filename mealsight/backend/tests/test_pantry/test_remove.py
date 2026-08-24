"""Tests for mealsight.pantry.remove.remove_items."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.pantry.models import PantryItemInput, RemovalItemInput
from mealsight.pantry.remove import remove_items
from mealsight.pantry.update import update_pantry


async def _seed_pantry_item(pantry_db: Database, name: str, quantity: float) -> None:
    await update_pantry(
        [PantryItemInput(name=name, quantity=quantity, unit="count", category="vegetable")],
        pantry_db=pantry_db,
        synonym_map={},
    )


async def test_normal_removal_decreases_quantity(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "onion", 5.0)

    result = await remove_items(
        [RemovalItemInput(name="onion", quantity_used=2.0)], pantry_db=pantry_db, synonym_map={}
    )

    detail = result.details[0]
    assert detail.quantity_removed == 2.0
    assert detail.quantity_remaining == 3.0
    assert detail.discrepancy == 0.0
    assert detail.deleted is False

    row = await pantry_db.fetch_one("SELECT quantity FROM pantry WHERE name = 'onion'")
    assert row is not None
    assert row["quantity"] == 3.0


async def test_removing_everything_deletes_the_row(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "onion", 2.0)

    result = await remove_items(
        [RemovalItemInput(name="onion", quantity_used=2.0)], pantry_db=pantry_db, synonym_map={}
    )

    assert result.details[0].deleted is True
    row = await pantry_db.fetch_one("SELECT * FROM pantry WHERE name = 'onion'")
    assert row is None


async def test_over_removal_clamps_at_zero_and_reports_the_discrepancy(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "onion", 2.0)

    result = await remove_items(
        [RemovalItemInput(name="onion", quantity_used=5.0)], pantry_db=pantry_db, synonym_map={}
    )

    detail = result.details[0]
    assert detail.quantity_removed == 2.0  # clamped, never more than what was there
    assert detail.discrepancy == 3.0  # 5 requested - 2 actually removed
    assert detail.quantity_remaining == 0.0
    assert detail.deleted is True

    row = await pantry_db.fetch_one("SELECT * FROM pantry WHERE name = 'onion'")
    assert row is None


async def test_removing_an_item_not_in_the_pantry_is_reported_not_found(pantry_db: Database) -> None:
    result = await remove_items(
        [RemovalItemInput(name="unobtainium", quantity_used=1.0)], pantry_db=pantry_db, synonym_map={}
    )

    detail = result.details[0]
    assert detail.found is False
    assert detail.discrepancy == 1.0


async def test_consumption_log_is_written_on_removal_with_the_recipe(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "onion", 5.0)

    await remove_items(
        [RemovalItemInput(name="onion", quantity_used=2.0, used_for_recipe="Onion Soup")],
        pantry_db=pantry_db,
        synonym_map={},
    )

    row = await pantry_db.fetch_one(
        "SELECT item_name, quantity_used, used_for_recipe FROM consumption_log WHERE item_name = 'onion'"
    )
    assert row is not None
    assert row["quantity_used"] == 2.0
    assert row["used_for_recipe"] == "Onion Soup"


async def test_consumption_log_records_only_the_actual_clamped_amount(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "onion", 2.0)

    await remove_items(
        [RemovalItemInput(name="onion", quantity_used=10.0)], pantry_db=pantry_db, synonym_map={}
    )

    row = await pantry_db.fetch_one("SELECT quantity_used FROM consumption_log WHERE item_name = 'onion'")
    assert row is not None
    assert row["quantity_used"] == 2.0


async def test_not_found_item_is_not_logged_to_consumption(pantry_db: Database) -> None:
    await remove_items(
        [RemovalItemInput(name="unobtainium", quantity_used=1.0)], pantry_db=pantry_db, synonym_map={}
    )

    rows = await pantry_db.fetch_all("SELECT * FROM consumption_log")
    assert rows == []
