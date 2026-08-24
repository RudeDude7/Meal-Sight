"""Tests for mealsight.user_intelligence.meal_history."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mealsight.db.connection import Database
from mealsight.user_intelligence.meal_history import get_meal_history, log_meal, rate_meal


async def test_log_meal_happy_path(user_db: Database, recipe_db: Database) -> None:
    meal = await log_meal(
        "recipe-1",
        "Chicken Stir Fry",
        "chinese",
        "dinner",
        date.today(),
        user_db=user_db,
        recipe_db=recipe_db,
    )

    assert meal.id > 0
    assert meal.recipe_name == "Chicken Stir Fry"
    assert meal.rating is None


async def test_log_meal_rejects_out_of_range_rating(user_db: Database, recipe_db: Database) -> None:
    with pytest.raises(ValueError, match="rating"):
        await log_meal(
            "recipe-1", "Test", None, None, date.today(), rating=6, user_db=user_db, recipe_db=recipe_db
        )


async def test_log_meal_accepts_no_rating(user_db: Database, recipe_db: Database) -> None:
    meal = await log_meal(
        "recipe-1", "Test", None, None, date.today(), rating=None, user_db=user_db, recipe_db=recipe_db
    )
    assert meal.rating is None


async def test_rate_meal_happy_path(user_db: Database, recipe_db: Database) -> None:
    meal = await log_meal(
        "recipe-1", "Test", "italian", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )

    rated = await rate_meal(meal.id, 4, user_db=user_db, recipe_db=recipe_db)

    assert rated.rating == 4


async def test_rate_meal_rejects_out_of_range_rating(user_db: Database, recipe_db: Database) -> None:
    meal = await log_meal("recipe-1", "Test", None, None, date.today(), user_db=user_db, recipe_db=recipe_db)

    with pytest.raises(ValueError, match="rating"):
        await rate_meal(meal.id, 0, user_db=user_db, recipe_db=recipe_db)


async def test_rate_meal_unknown_meal_id_raises(user_db: Database, recipe_db: Database) -> None:
    with pytest.raises(ValueError, match="99999"):
        await rate_meal(99999, 5, user_db=user_db, recipe_db=recipe_db)


async def test_get_meal_history_orders_most_recent_first(user_db: Database, recipe_db: Database) -> None:
    today = date.today()
    await log_meal(
        "recipe-1", "Older", None, None, today - timedelta(days=2), user_db=user_db, recipe_db=recipe_db
    )
    await log_meal("recipe-2", "Newer", None, None, today, user_db=user_db, recipe_db=recipe_db)

    history = await get_meal_history(days_back=14, user_db=user_db)

    assert [meal.recipe_name for meal in history] == ["Newer", "Older"]


async def test_get_meal_history_filters_by_cuisine_and_rating(user_db: Database, recipe_db: Database) -> None:
    today = date.today()
    await log_meal(
        "recipe-1", "Thai", "thai", None, today, rating=5, user_db=user_db, recipe_db=recipe_db
    )
    await log_meal(
        "recipe-2", "Italian", "italian", None, today, rating=2, user_db=user_db, recipe_db=recipe_db
    )

    history = await get_meal_history(cuisine_filter="thai", user_db=user_db)
    assert [meal.recipe_name for meal in history] == ["Thai"]

    history = await get_meal_history(rating_filter=2, user_db=user_db)
    assert [meal.recipe_name for meal in history] == ["Italian"]


async def test_get_meal_history_empty_database_returns_empty_list(user_db: Database) -> None:
    history = await get_meal_history(user_db=user_db)
    assert history == []
