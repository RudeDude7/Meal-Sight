"""Tests for mealsight.user_intelligence.profile.get_user_profile."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.user_intelligence.profile import get_user_profile


async def test_fresh_database_returns_a_usable_default_profile(user_db: Database) -> None:
    profile = await get_user_profile(user_db=user_db)

    assert profile.dietary_restrictions == []
    assert profile.disliked_ingredients == []
    assert profile.preferred_cook_time_minutes > 0
    assert profile.household_size >= 1
    assert profile.protein_preference is None
    assert profile.cooking_skill in ("beginner", "intermediate", "advanced")
    assert profile.budget_sensitivity in ("budget", "moderate", "flexible")
    assert profile.cuisine_preferences == {}


async def test_cuisine_preferences_empty_with_no_ratings_rather_than_erroring(user_db: Database) -> None:
    profile = await get_user_profile(user_db=user_db)
    assert profile.cuisine_preferences == {}


async def test_cuisine_preferences_reads_live_from_preference_scores(user_db: Database) -> None:
    await user_db.execute(
        "INSERT INTO preference_scores (dimension, value, score, data_points) VALUES (?, ?, ?, ?)",
        ("cuisine", "italian", 0.8, 5),
    )
    await user_db.execute(
        "INSERT INTO preference_scores (dimension, value, score, data_points) VALUES (?, ?, ?, ?)",
        ("cuisine", "thai", 0.4, 2),
    )
    # A different dimension must not leak into cuisine_preferences.
    await user_db.execute(
        "INSERT INTO preference_scores (dimension, value, score, data_points) VALUES (?, ?, ?, ?)",
        ("protein", "chicken", 0.9, 3),
    )

    profile = await get_user_profile(user_db=user_db)

    assert profile.cuisine_preferences == {"italian": 0.8, "thai": 0.4}
