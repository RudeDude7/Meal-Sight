"""Tests for mealsight.user_intelligence.scoring.recompute_preference_scores,
triggered indirectly through log_meal/rate_meal exactly as production
code triggers it."""

from __future__ import annotations

from datetime import date

from mealsight.db.connection import Database
from mealsight.user_intelligence.meal_history import log_meal, rate_meal
from tests.test_user_intelligence.conftest import insert_recipe

_NEUTRAL_SCORE = 0.5


async def _cuisine_scores(user_db: Database) -> dict[str, tuple[float, int]]:
    rows = await user_db.fetch_all(
        "SELECT value, score, data_points FROM preference_scores WHERE dimension = 'cuisine'"
    )
    return {row["value"]: (row["score"], row["data_points"]) for row in rows}


async def test_scores_recompute_across_all_rated_meals_not_just_the_new_one(
    user_db: Database, recipe_db: Database
) -> None:
    meal_one = await log_meal(
        None, "Meal 1", "thai", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )
    await rate_meal(meal_one.id, 5, user_db=user_db, recipe_db=recipe_db)

    meal_two = await log_meal(
        None, "Meal 2", "thai", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )
    await rate_meal(meal_two.id, 5, user_db=user_db, recipe_db=recipe_db)

    scores = await _cuisine_scores(user_db)

    # Both ratings — the one from meal_one AND the new one from meal_two
    # — must both be reflected: data_points is 2, not 1.
    assert scores["thai"][1] == 2


async def test_low_data_points_shrinks_toward_neutral_more_than_high(
    user_db: Database, recipe_db: Database
) -> None:
    solo = await log_meal(
        None, "Solo", "italian", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )
    await rate_meal(solo.id, 5, user_db=user_db, recipe_db=recipe_db)

    for i in range(10):
        meal = await log_meal(
            None, f"Repeat {i}", "japanese", None, date.today(), user_db=user_db, recipe_db=recipe_db
        )
        await rate_meal(meal.id, 5, user_db=user_db, recipe_db=recipe_db)

    scores = await _cuisine_scores(user_db)
    italian_score, italian_points = scores["italian"]
    japanese_score, japanese_points = scores["japanese"]

    assert italian_points == 1
    assert japanese_points == 10
    # Same raw mean (all 5-star) — the 1-rating cuisine must land
    # visibly closer to neutral (0.5) than the 10-rating cuisine.
    assert (italian_score - _NEUTRAL_SCORE) < (japanese_score - _NEUTRAL_SCORE)
    assert italian_score < japanese_score


async def test_unrated_meals_are_excluded_from_scoring(user_db: Database, recipe_db: Database) -> None:
    await log_meal(None, "Unrated", "mexican", None, date.today(), user_db=user_db, recipe_db=recipe_db)
    rated = await log_meal(
        None, "Rated", "mexican", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )
    await rate_meal(rated.id, 4, user_db=user_db, recipe_db=recipe_db)

    scores = await _cuisine_scores(user_db)

    assert scores["mexican"][1] == 1


async def test_protein_score_derived_from_recipe_ingredients(user_db: Database, recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="r1", name="Chicken Curry", cuisine="indian", ingredients=["chicken", "rice"]
    )
    meal = await log_meal(
        "r1", "Chicken Curry", "indian", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )
    await rate_meal(meal.id, 5, user_db=user_db, recipe_db=recipe_db)

    rows = await user_db.fetch_all(
        "SELECT value, data_points FROM preference_scores WHERE dimension = 'protein'"
    )
    values = {row["value"]: row["data_points"] for row in rows}
    assert values.get("chicken") == 1
