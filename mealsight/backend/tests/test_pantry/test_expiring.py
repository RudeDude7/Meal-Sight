"""Tests for mealsight.pantry.expiring.flag_expiring."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.pantry.expiring import flag_expiring


async def _insert_raw(
    pantry_db: Database,
    name: str,
    category: str,
    estimated_shelf_days: int | None,
    added_days_ago: int,
) -> None:
    await pantry_db.execute(
        f"""
        INSERT INTO pantry (name, quantity, unit, category, freshness_status, estimated_shelf_days,
                            added_date, last_seen_date)
        VALUES (?, 1.0, 'count', ?, 'fresh', ?, datetime('now', '-{added_days_ago} days'),
                datetime('now', '-{added_days_ago} days'))
        """,
        (name, category, estimated_shelf_days),
    )


async def test_empty_pantry_returns_empty_list_rather_than_erroring(pantry_db: Database) -> None:
    result = await flag_expiring(pantry_db=pantry_db)
    assert result == []


async def test_orders_by_urgency_with_already_expired_items_first(pantry_db: Database) -> None:
    # shelf 5, added 2 days ago -> 3 days remaining.
    await _insert_raw(pantry_db, "carrot", "vegetable", estimated_shelf_days=5, added_days_ago=2)
    # shelf 3, added 5 days ago -> -2 days remaining (already expired).
    await _insert_raw(pantry_db, "spinach", "vegetable", estimated_shelf_days=3, added_days_ago=5)
    # shelf 2, added 1 day ago -> 1 day remaining.
    await _insert_raw(pantry_db, "milk", "dairy", estimated_shelf_days=2, added_days_ago=1)

    results = await flag_expiring(days_threshold=3, pantry_db=pantry_db)

    names_in_order = [item.name for item in results]
    assert names_in_order == ["spinach", "milk", "carrot"]
    assert results[0].days_remaining < 0


async def test_already_expired_item_gets_a_distinct_action(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "spinach", "vegetable", estimated_shelf_days=3, added_days_ago=10)

    results = await flag_expiring(days_threshold=3, pantry_db=pantry_db)

    assert len(results) == 1
    assert "expired" in results[0].suggested_action


async def test_item_expiring_today_or_tomorrow_says_use_today(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "milk", "dairy", estimated_shelf_days=1, added_days_ago=0)

    results = await flag_expiring(days_threshold=3, pantry_db=pantry_db)

    assert results[0].suggested_action == "use today"


async def test_freezable_item_with_a_few_days_left_suggests_freezing(pantry_db: Database) -> None:
    # "protein" category default has a real shelf_days_frozen value.
    await _insert_raw(pantry_db, "chicken", "protein", estimated_shelf_days=5, added_days_ago=2)

    results = await flag_expiring(days_threshold=5, pantry_db=pantry_db)

    assert results[0].suggested_action == "freeze to extend"


async def test_items_outside_the_threshold_are_excluded(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "rice", "grain", estimated_shelf_days=730, added_days_ago=0)

    results = await flag_expiring(days_threshold=3, pantry_db=pantry_db)

    assert results == []


async def test_items_with_unknown_shelf_life_are_excluded(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "mystery", "vegetable", estimated_shelf_days=None, added_days_ago=0)

    results = await flag_expiring(days_threshold=3, pantry_db=pantry_db)

    assert results == []
