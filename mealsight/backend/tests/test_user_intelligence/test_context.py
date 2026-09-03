"""Tests for mealsight.user_intelligence.context.get_context_signals and
record_cooking_pattern (also exercised indirectly through log_meal)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from mealsight.db.connection import Database
from mealsight.user_intelligence import context as context_module
from mealsight.user_intelligence.context import get_context_signals
from mealsight.user_intelligence.meal_history import log_meal
from mealsight.utils.weather import WeatherSnapshot


async def test_meal_type_boundaries(user_db: Database) -> None:
    cases = [
        (5, "breakfast"),
        (10, "breakfast"),
        (11, "lunch"),
        (14, "lunch"),
        (15, "snack"),
        (16, "snack"),
        (17, "dinner"),
        (20, "dinner"),
        (21, "snack"),
        (4, "snack"),
    ]
    for hour, expected in cases:
        result = await get_context_signals(
            current_time=datetime(2026, 1, 5, hour, 0), day_of_week=0, user_db=user_db
        )
        assert result.meal_type == expected, f"hour {hour} expected {expected}, got {result.meal_type}"


async def test_complexity_suggestion_differs_weekday_versus_weekend(user_db: Database) -> None:
    monday = await get_context_signals(
        current_time=datetime(2026, 1, 5, 18, 0), day_of_week=0, user_db=user_db
    )
    friday = await get_context_signals(
        current_time=datetime(2026, 1, 9, 18, 0), day_of_week=4, user_db=user_db
    )
    saturday = await get_context_signals(
        current_time=datetime(2026, 1, 10, 18, 0), day_of_week=5, user_db=user_db
    )

    assert "quick" in monday.complexity_suggestion.lower()
    assert "elaborate" in friday.complexity_suggestion.lower()
    assert "elaborate" in saturday.complexity_suggestion.lower()


async def test_empty_cooking_patterns_returns_sensible_note(user_db: Database) -> None:
    result = await get_context_signals(
        current_time=datetime(2026, 1, 5, 18, 0), day_of_week=0, user_db=user_db
    )

    assert len(result.context_notes) == 1
    assert "no cooking history" in result.context_notes[0].lower()


async def test_cooking_patterns_populated_by_log_meal(user_db: Database, recipe_db: Database) -> None:
    await log_meal(
        None, "Test", "italian", None, date.today(), user_db=user_db, recipe_db=recipe_db
    )

    rows = await user_db.fetch_all("SELECT day_of_week, hour_of_day, cook_count FROM cooking_patterns")
    assert len(rows) == 1
    assert rows[0]["cook_count"] == 1


async def test_cooking_patterns_cook_count_increments_across_calls(
    user_db: Database, recipe_db: Database
) -> None:
    await log_meal(None, "Test 1", "italian", None, date.today(), user_db=user_db, recipe_db=recipe_db)
    await log_meal(None, "Test 2", "italian", None, date.today(), user_db=user_db, recipe_db=recipe_db)

    rows = await user_db.fetch_all("SELECT cook_count FROM cooking_patterns")
    # Both calls happen within the same test run (same real hour), so
    # they land in the same day/hour cell.
    assert len(rows) == 1
    assert rows[0]["cook_count"] == 2


async def test_weather_absent_degrades_to_todays_behavior_exactly(
    user_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    # get_current_weather already returns None whenever no key is
    # configured or the lookup fails — monkeypatching the imported name
    # directly is the simplest, most direct way to exercise "weather
    # unavailable" here without touching the network at all.
    async def _no_weather() -> WeatherSnapshot | None:
        return None

    monkeypatch.setattr(context_module, "get_current_weather", _no_weather)

    result = await get_context_signals(
        current_time=datetime(2026, 1, 5, 18, 0), day_of_week=0, user_db=user_db
    )

    assert result.temperature_f is None
    assert result.conditions is None
    assert result.mood_suggestion is None
    # Every field that existed before this feature is completely
    # unaffected by weather being unavailable.
    assert result.meal_type == "dinner"
    assert "quick" in result.complexity_suggestion.lower()
    assert len(result.context_notes) == 1


async def test_weather_present_populates_all_three_fields_together(
    user_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_weather() -> WeatherSnapshot | None:
        return WeatherSnapshot(
            temperature_f=28.0, conditions="light snow", mood_suggestion="warm, hearty, comforting"
        )

    monkeypatch.setattr(context_module, "get_current_weather", _fake_weather)

    result = await get_context_signals(
        current_time=datetime(2026, 1, 5, 18, 0), day_of_week=0, user_db=user_db
    )

    assert result.temperature_f == 28.0
    assert result.conditions == "light snow"
    assert result.mood_suggestion == "warm, hearty, comforting"
