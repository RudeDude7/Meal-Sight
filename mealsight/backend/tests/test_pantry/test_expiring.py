"""Tests for mealsight.pantry.expiring.flag_expiring."""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.pantry.expiring import flag_expiring, split_usable_and_waste, usable_pantry_names


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


def test_split_keeps_items_within_the_grace_window_and_flags_the_rest_as_waste() -> None:
    grace = settings.expired_grace_days
    items = [
        {"name": "chicken", "days_remaining": 2, "quantity": 1.0, "unit": "whole"},
        {"name": "egg", "days_remaining": -grace, "quantity": 3.0, "unit": "count"},
        {"name": "milk", "days_remaining": -(grace + 1), "quantity": 2.0, "unit": "l"},
        {"name": "chicken thigh", "days_remaining": -51, "quantity": None, "unit": None},
    ]

    usable, waste = split_usable_and_waste(items)

    assert [i["name"] for i in usable] == ["chicken", "egg"]
    assert [i["name"] for i in waste] == ["milk", "chicken thigh"]
    assert waste[0]["days_overdue"] == grace + 1
    assert waste[1]["days_overdue"] == 51
    # carries the existing log_waste tool's own arguments; never logs by itself
    assert waste[0]["log_waste_args"] == {
        "item_name": "milk",
        "quantity_wasted": 2.0,
        "unit": "l",
        "reason": "expired",
    }
    assert waste[1]["log_waste_args"]["quantity_wasted"] is None


def test_split_grace_days_can_be_overridden_and_unknown_expiry_is_left_alone() -> None:
    items = [{"name": "rice", "days_remaining": None}, {"name": "milk", "days_remaining": -5}]

    usable, waste = split_usable_and_waste(items, grace_days=7)

    assert [i["name"] for i in usable] == ["rice", "milk"]
    assert waste == []


def test_usable_pantry_names_uses_the_same_cutoff_as_the_waste_split() -> None:
    grace = settings.expired_grace_days
    items = [
        {"name": "ok", "days_remaining": 3},
        {"name": "edge", "days_remaining": -grace},
        {"name": "gone", "days_remaining": -(grace + 1)},
        {"name": "unknown", "days_remaining": None},
    ]

    usable, waste = split_usable_and_waste(items)

    assert usable_pantry_names(items) == ["ok", "edge", "unknown"]
    assert [i["name"] for i in waste] == ["gone"]
