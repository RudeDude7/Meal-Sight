"""Tests for mealsight.user_intelligence.taste_insights.get_taste_insights."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.user_intelligence.meal_history import log_meal
from mealsight.user_intelligence.taste_insights import get_taste_insights

from .conftest import insert_recipe


async def _log_meal_at(
    user_db: Database,
    cooked_at: datetime,
    *,
    recipe_id: str | None,
    recipe_name: str,
    cuisine: str | None,
    rating: int | None = None,
) -> None:
    """log_meal itself always stamps cooked_at as CURRENT_TIMESTAMP —
    real backdating (needed to test time_range window filtering)
    requires a direct insert instead."""
    await user_db.execute(
        "INSERT INTO meal_history (recipe_id, recipe_name, cuisine, meal_type, date, rating, cooked_at) "
        "VALUES (?, ?, ?, 'dinner', ?, ?, ?)",
        (
            recipe_id,
            recipe_name,
            cuisine,
            cooked_at.date().isoformat(),
            rating,
            cooked_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


async def _log_n_meals(
    user_db: Database, recipe_db: Database, n: int, *, cuisine: str = "italian"
) -> None:
    await insert_recipe(recipe_db, recipe_id="r-filler", name="Filler", cuisine=cuisine, ingredients=[])
    for _ in range(n):
        await log_meal(
            "r-filler", "Filler", cuisine, "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
        )


# --------------------------------------------------------------------
# insufficient history
# --------------------------------------------------------------------


async def test_insufficient_history_returns_a_clear_message_not_statistics(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await _log_n_meals(user_db, recipe_db, settings.min_meals_for_insights - 1)

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert result.sufficient_history is False
    assert result.message is not None
    assert str(settings.min_meals_for_insights) in result.message
    assert result.total_meals_cooked == settings.min_meals_for_insights - 1
    assert result.most_cooked_cuisine is None
    assert result.protein_variety_score is None
    assert result.suggestions == []


async def test_exactly_the_minimum_meal_count_is_sufficient(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await _log_n_meals(user_db, recipe_db, settings.min_meals_for_insights)

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert result.sufficient_history is True
    assert result.message is None


# --------------------------------------------------------------------
# protein variety score
# --------------------------------------------------------------------


async def test_protein_variety_scores_a_skewed_distribution_lower_than_an_even_one(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    # Skewed: 9 chicken, 1 beef.
    await insert_recipe(recipe_db, recipe_id="chicken-r", name="Chicken", ingredients=["chicken breast"])
    await insert_recipe(recipe_db, recipe_id="beef-r", name="Beef", ingredients=["beef"])
    for _ in range(9):
        await log_meal(
            "chicken-r", "Chicken", "american", "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
        )
    await log_meal(
        "beef-r", "Beef", "american", "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
    )
    skewed = await get_taste_insights(
        "all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db
    )

    # Even: 5 chicken, 5 beef — fresh databases for a clean comparison.
    import pathlib

    from mealsight.db.connection import SCHEMA_DIR
    from mealsight.db.init import init_database

    even_user_db = Database(
        pathlib.Path(user_db.path).parent / "even_user.db", name="user_intelligence",
        schema_path=SCHEMA_DIR / "user_intelligence.sql",
    )
    await init_database(even_user_db, even_user_db.schema_path)
    for _ in range(5):
        await log_meal(
            "chicken-r", "Chicken", "american", "dinner", date.today(),
            user_db=even_user_db, recipe_db=recipe_db,
        )
        await log_meal(
            "beef-r", "Beef", "american", "dinner", date.today(),
            user_db=even_user_db, recipe_db=recipe_db,
        )
    even = await get_taste_insights(
        "all_time", user_db=even_user_db, recipe_db=recipe_db, pantry_db=pantry_db
    )
    await even_user_db.close()

    assert skewed.protein_variety_score is not None
    assert even.protein_variety_score is not None
    assert skewed.protein_variety_score < even.protein_variety_score
    assert even.protein_variety_score == 1.0


async def test_a_single_protein_scores_zero_variety(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await insert_recipe(recipe_db, recipe_id="chicken-r", name="Chicken", ingredients=["chicken breast"])
    for _ in range(5):
        await log_meal(
            "chicken-r", "Chicken", "american", "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
        )
    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)
    assert result.protein_variety_score == 0.0


# --------------------------------------------------------------------
# suggestions: real cuisines and counts
# --------------------------------------------------------------------


async def test_cuisine_dominance_suggestion_names_real_cuisine_and_count(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await insert_recipe(recipe_db, recipe_id="it-1", name="Pasta", cuisine="italian", ingredients=[])
    await insert_recipe(recipe_db, recipe_id="mx-1", name="Tacos", cuisine="mexican", ingredients=[])
    for _ in range(6):
        await log_meal(
            "it-1", "Pasta", "italian", "dinner", date.today(), rating=4,
            user_db=user_db, recipe_db=recipe_db,
        )
    for _ in range(2):
        await log_meal(
            "mx-1", "Tacos", "mexican", "dinner", date.today(), rating=5,
            user_db=user_db, recipe_db=recipe_db,
        )

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert result.most_cooked_cuisine == "italian"
    cuisine_suggestion = next((s for s in result.suggestions if "italian" in s), None)
    assert cuisine_suggestion is not None
    assert "6" in cuisine_suggestion
    assert "8" in cuisine_suggestion  # total meals
    assert "mexican" in cuisine_suggestion


async def test_no_cuisine_dominance_suggestion_when_no_cuisine_reaches_half(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    # Three cuisines, two meals each — no single cuisine reaches the
    # 50% dominance threshold (matching repetition.py's own identical
    # _CUISINE_DOMINANCE_THRESHOLD precedent: exactly 50% DOES count as
    # dominant there too, so a genuine non-dominant split needs a THIRD
    # cuisine splitting the remainder, not just an even 50/50 split).
    for cuisine, recipe_id in (("italian", "it-1"), ("mexican", "mx-1"), ("thai", "th-1")):
        await insert_recipe(recipe_db, recipe_id=recipe_id, name=recipe_id, cuisine=cuisine, ingredients=[])
        for _ in range(2):
            await log_meal(
                recipe_id, recipe_id, cuisine, "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
            )
    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)
    assert not any("of your last" in s for s in result.suggestions)


# --------------------------------------------------------------------
# waste correlation
# --------------------------------------------------------------------


async def test_waste_correlation_fires_above_threshold(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await _log_n_meals(user_db, recipe_db, settings.min_meals_for_insights, cuisine="italian")
    for _ in range(settings.waste_insight_threshold):
        await pantry_db.execute(
            "INSERT INTO waste_log (item_name, quantity_wasted, unit, reason) "
            "VALUES (?, 1.0, 'bunch', 'expired')",
            ("cilantro",),
        )

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    waste_suggestion = next((s for s in result.suggestions if "cilantro" in s), None)
    assert waste_suggestion is not None
    assert str(settings.waste_insight_threshold) in waste_suggestion


async def test_waste_correlation_does_not_fire_below_threshold(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await _log_n_meals(user_db, recipe_db, settings.min_meals_for_insights)
    for _ in range(settings.waste_insight_threshold - 1):
        await pantry_db.execute(
            "INSERT INTO waste_log (item_name, quantity_wasted, unit, reason) "
            "VALUES (?, 1.0, 'bunch', 'expired')",
            ("cilantro",),
        )

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert not any("cilantro" in s for s in result.suggestions)


async def test_waste_correlation_does_not_fire_when_ingredient_is_actually_cooked_with(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await insert_recipe(
        recipe_db, recipe_id="cilantro-r", name="Cilantro Lime Rice", cuisine="mexican",
        ingredients=["cilantro", "rice"],
    )
    for _ in range(settings.min_meals_for_insights + 5):
        await log_meal(
            "cilantro-r", "Cilantro Lime Rice", "mexican", "dinner", date.today(),
            user_db=user_db, recipe_db=recipe_db,
        )
    for _ in range(settings.waste_insight_threshold):
        await pantry_db.execute(
            "INSERT INTO waste_log (item_name, quantity_wasted, unit, reason) "
            "VALUES (?, 1.0, 'bunch', 'expired')",
            ("cilantro",),
        )

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert not any("cilantro" in s for s in result.suggestions)


# --------------------------------------------------------------------
# time_range window filtering
# --------------------------------------------------------------------


async def test_this_week_excludes_meals_from_last_month(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    await insert_recipe(recipe_db, recipe_id="r1", name="R1", cuisine="italian", ingredients=[])
    for _ in range(settings.min_meals_for_insights):
        await _log_meal_at(user_db, now, recipe_id="r1", recipe_name="R1", cuisine="italian")
    for _ in range(settings.min_meals_for_insights):
        await _log_meal_at(
            user_db, now - timedelta(days=40), recipe_id="r1", recipe_name="R1", cuisine="italian"
        )

    result = await get_taste_insights(
        "this_week", current_time=now, user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db
    )
    assert result.total_meals_cooked == settings.min_meals_for_insights


# --------------------------------------------------------------------
# actual vs stated preferred cook time
# --------------------------------------------------------------------


async def test_preferred_cook_time_is_derived_from_actual_cooked_meals(
    user_db: Database, recipe_db: Database, pantry_db: Database
) -> None:
    await insert_recipe(recipe_db, recipe_id="quick", name="Quick", ingredients=[])
    await recipe_db.execute("UPDATE recipes SET cook_time_minutes = 10 WHERE id = 'quick'")
    for _ in range(settings.min_meals_for_insights):
        await log_meal(
            "quick", "Quick", "italian", "dinner", date.today(), user_db=user_db, recipe_db=recipe_db
        )

    result = await get_taste_insights("all_time", user_db=user_db, recipe_db=recipe_db, pantry_db=pantry_db)

    assert result.preferred_cook_time_minutes == 10
    # Default stated profile preference is 30 minutes — genuinely different.
    assert result.stated_preferred_cook_time_minutes == 30
    assert any("10" in s and "30" in s for s in result.suggestions)
