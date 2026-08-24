"""Tests for mealsight.pantry.query.get_pantry."""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.pantry.query import get_pantry


async def _insert_raw(
    pantry_db: Database,
    name: str,
    category: str,
    freshness_status: str,
    estimated_shelf_days: int | None,
    added_days_ago: int,
) -> None:
    await pantry_db.execute(
        f"""
        INSERT INTO pantry (name, quantity, unit, category, freshness_status, estimated_shelf_days,
                            added_date, last_seen_date)
        VALUES (?, 1.0, 'count', ?, ?, ?, datetime('now', '-{added_days_ago} days'),
                datetime('now', '-{added_days_ago} days'))
        """,
        (name, category, freshness_status, estimated_shelf_days),
    )


async def test_expiring_soon_includes_items_within_the_threshold(pantry_db: Database) -> None:
    # shelf 3 days, added 2 days ago -> 1 day remaining, within expiring_soon_days (3).
    await _insert_raw(pantry_db, "milk", "dairy", "fresh", estimated_shelf_days=3, added_days_ago=2)
    # shelf 30 days, added 1 day ago -> 29 days remaining, well outside the window.
    await _insert_raw(pantry_db, "rice", "grain", "fresh", estimated_shelf_days=30, added_days_ago=1)

    results = await get_pantry(freshness_filter="expiring_soon", pantry_db=pantry_db)

    names = {item.name for item in results}
    assert names == {"milk"}
    assert results[0].days_remaining is not None
    assert results[0].days_remaining <= settings.expiring_soon_days


async def test_expiring_soon_excludes_items_with_unknown_shelf_life(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "mystery", "vegetable", "fresh", estimated_shelf_days=None, added_days_ago=0)

    results = await get_pantry(freshness_filter="expiring_soon", pantry_db=pantry_db)

    assert results == []


async def test_fresh_filter_matches_only_stored_fresh_status(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "onion", "vegetable", "fresh", estimated_shelf_days=30, added_days_ago=0)
    await _insert_raw(pantry_db, "lettuce", "vegetable", "wilted", estimated_shelf_days=7, added_days_ago=0)

    results = await get_pantry(freshness_filter="fresh", pantry_db=pantry_db)

    assert {item.name for item in results} == {"onion"}


async def test_all_filter_returns_everything(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "onion", "vegetable", "fresh", estimated_shelf_days=30, added_days_ago=0)
    await _insert_raw(pantry_db, "lettuce", "vegetable", "wilted", estimated_shelf_days=7, added_days_ago=0)

    results = await get_pantry(freshness_filter="all", pantry_db=pantry_db)

    assert {item.name for item in results} == {"onion", "lettuce"}


async def test_category_filter(pantry_db: Database) -> None:
    await _insert_raw(pantry_db, "onion", "vegetable", "fresh", estimated_shelf_days=30, added_days_ago=0)
    await _insert_raw(pantry_db, "milk", "dairy", "fresh", estimated_shelf_days=7, added_days_ago=0)

    results = await get_pantry(category="dairy", pantry_db=pantry_db)

    assert {item.name for item in results} == {"milk"}


async def test_search_matches_a_substring_of_the_stored_name(pantry_db: Database) -> None:
    await _insert_raw(
        pantry_db, "green onion", "vegetable", "fresh", estimated_shelf_days=7, added_days_ago=0
    )
    await _insert_raw(pantry_db, "milk", "dairy", "fresh", estimated_shelf_days=7, added_days_ago=0)

    results = await get_pantry(search="onion", pantry_db=pantry_db)

    assert {item.name for item in results} == {"green onion"}
