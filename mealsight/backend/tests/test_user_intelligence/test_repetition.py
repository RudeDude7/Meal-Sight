"""Tests for mealsight.user_intelligence.repetition.check_repetition."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.user_intelligence.meal_history import log_meal
from mealsight.user_intelligence.repetition import check_repetition
from tests.test_user_intelligence.conftest import insert_recipe


async def _log_chicken_meal(user_db: Database, recipe_db: Database, index: int) -> None:
    recipe_id = f"other-{index}"
    name = f"Chicken Dish {index}"
    await insert_recipe(
        recipe_db, recipe_id=recipe_id, name=name, cuisine="american", ingredients=["chicken"]
    )
    await log_meal(recipe_id, name, "american", None, date.today(), user_db=user_db, recipe_db=recipe_db)


async def test_exact_repeat_within_window_scores_high(user_db: Database, recipe_db: Database) -> None:
    await insert_recipe(recipe_db, recipe_id="r1", name="Tacos", cuisine="mexican", ingredients=["beef"])
    await log_meal(
        "r1", "Tacos", "mexican", None, date.today() - timedelta(days=2), user_db=user_db, recipe_db=recipe_db
    )

    result = await check_repetition("r1", check_window_days=7, user_db=user_db, recipe_db=recipe_db)

    assert result.recommendation == "too_repetitive"
    assert result.repetition_score == 1.0
    assert result.last_cooked == date.today() - timedelta(days=2)


async def test_exact_repeat_outside_window_does_not_score_high(
    user_db: Database, recipe_db: Database
) -> None:
    await insert_recipe(recipe_db, recipe_id="r1", name="Tacos", cuisine="mexican", ingredients=["beef"])
    await log_meal(
        "r1",
        "Tacos",
        "mexican",
        None,
        date.today() - timedelta(days=30),
        user_db=user_db,
        recipe_db=recipe_db,
    )

    result = await check_repetition("r1", check_window_days=7, user_db=user_db, recipe_db=recipe_db)

    assert result.recommendation != "too_repetitive"
    assert result.repetition_score < 1.0
    # last_cooked is independent of the window — it should still report.
    assert result.last_cooked == date.today() - timedelta(days=30)


async def test_protein_repetition_fires_at_the_configured_threshold(
    user_db: Database, recipe_db: Database
) -> None:
    await insert_recipe(
        recipe_db, recipe_id="candidate", name="Chicken Salad", cuisine="american", ingredients=["chicken"]
    )
    # One meal per other recipe, each also chicken — one more than
    # settings.max_same_protein_per_week, so the threshold is crossed.
    for i in range(settings.max_same_protein_per_week + 1):
        await _log_chicken_meal(user_db, recipe_db, i)

    result = await check_repetition("candidate", check_window_days=7, user_db=user_db, recipe_db=recipe_db)

    assert result.recommendation == "suggest_alternative"
    assert result.repetition_score == 0.7


async def test_protein_repetition_does_not_fire_below_the_threshold(
    user_db: Database, recipe_db: Database
) -> None:
    await insert_recipe(
        recipe_db, recipe_id="candidate", name="Chicken Salad", cuisine="american", ingredients=["chicken"]
    )
    for i in range(settings.max_same_protein_per_week):
        await _log_chicken_meal(user_db, recipe_db, i)

    result = await check_repetition("candidate", check_window_days=7, user_db=user_db, recipe_db=recipe_db)

    assert result.recommendation != "suggest_alternative" or result.repetition_score != 0.7


async def test_never_cooked_recipe_returns_acceptable_with_no_last_cooked(
    user_db: Database, recipe_db: Database
) -> None:
    await insert_recipe(recipe_db, recipe_id="fresh", name="New Recipe", cuisine="thai", ingredients=["tofu"])

    result = await check_repetition("fresh", user_db=user_db, recipe_db=recipe_db)

    assert result.recommendation == "acceptable"
    assert result.last_cooked is None


async def test_empty_history_does_not_error(user_db: Database, recipe_db: Database) -> None:
    await insert_recipe(recipe_db, recipe_id="fresh", name="New Recipe", cuisine="thai", ingredients=["tofu"])

    result = await check_repetition("fresh", user_db=user_db, recipe_db=recipe_db)

    assert result.repetition_score == 0.0


async def test_unknown_recipe_id_raises(user_db: Database, recipe_db: Database) -> None:
    with pytest.raises(ValueError, match="does-not-exist"):
        await check_repetition("does-not-exist", user_db=user_db, recipe_db=recipe_db)
