"""Tests for schema-level constraints — currently just the meal_history
rating CHECK, but this is the home for any future ones too."""

from __future__ import annotations

import aiosqlite
import pytest

from mealsight.db.connection import Database
from mealsight.db.init import init_database


async def _insert_meal(db: Database, rating: int | None) -> None:
    await db.execute(
        "INSERT INTO meal_history (recipe_name, date, rating) VALUES (?, ?, ?)",
        ("Test Recipe", "2026-01-01", rating),
    )


@pytest.mark.parametrize("bad_rating", [0, 6, -1, 100])
async def test_rating_check_rejects_out_of_range_values(user_db: Database, bad_rating: int) -> None:
    await init_database(user_db, user_db.schema_path)

    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_meal(user_db, bad_rating)


@pytest.mark.parametrize("good_rating", [1, 5, 3])
async def test_rating_check_accepts_in_range_values(user_db: Database, good_rating: int) -> None:
    await init_database(user_db, user_db.schema_path)

    await _insert_meal(user_db, good_rating)

    row = await user_db.fetch_one("SELECT rating FROM meal_history WHERE recipe_name = ?", ("Test Recipe",))
    assert row is not None
    assert row["rating"] == good_rating


async def test_rating_check_accepts_null(user_db: Database) -> None:
    await init_database(user_db, user_db.schema_path)

    await _insert_meal(user_db, None)

    row = await user_db.fetch_one("SELECT rating FROM meal_history WHERE recipe_name = ?", ("Test Recipe",))
    assert row is not None
    assert row["rating"] is None
