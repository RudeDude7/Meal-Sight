"""Converts mealsight.user_intelligence pydantic result models into
plain, JSON-serializable dicts with a stable shape — what the
user-intelligence MCP tools actually return — plus the structured error
shapes every tool returns instead of letting an exception escape.
"""

from __future__ import annotations

from typing import Any

from mealsight.mcp_servers.errors import internal_error, not_found_error, validation_error
from mealsight.user_intelligence.models import ContextSignals, MealRecord, RepetitionCheck, UserProfile

__all__ = [
    "context_signals_to_dict",
    "internal_error",
    "meal_history_to_dict",
    "meal_record_to_dict",
    "not_found_error",
    "repetition_check_to_dict",
    "user_profile_to_dict",
    "validation_error",
]


def user_profile_to_dict(profile: UserProfile) -> dict[str, Any]:
    """Shape: {"dietary_restrictions", "disliked_ingredients",
    "preferred_cook_time_minutes", "household_size", "protein_preference",
    "cooking_skill", "budget_sensitivity", "cuisine_preferences"}.
    cuisine_preferences is a {cuisine: score} mapping (0.0-1.0), empty
    when nothing has been rated yet."""
    return profile.model_dump(mode="json")


def meal_record_to_dict(meal: MealRecord) -> dict[str, Any]:
    """Shape: {"id", "recipe_id", "recipe_name", "cuisine", "meal_type",
    "date", "rating", "servings_made", "ingredients_used", "notes",
    "cooked_at"}. rating is null for a meal logged but not yet rated."""
    return meal.model_dump(mode="json")


def meal_history_to_dict(meals: list[MealRecord]) -> dict[str, Any]:
    """Shape: {"meals": [...], "count": int}, most recent first."""
    return {"meals": [meal.model_dump(mode="json") for meal in meals], "count": len(meals)}


def repetition_check_to_dict(check: RepetitionCheck) -> dict[str, Any]:
    """Shape: {"repetition_score", "reason", "recommendation",
    "last_cooked"}. recommendation is one of "acceptable",
    "suggest_alternative", "too_repetitive" — a signal to weigh, not a
    hard rule; see the check_repetition tool's own docstring."""
    return check.model_dump(mode="json")


def context_signals_to_dict(signals: ContextSignals) -> dict[str, Any]:
    """Shape: {"meal_type", "complexity_suggestion", "context_notes"}.
    context_notes is always at least one string, even with no cooking
    history at all."""
    return signals.model_dump(mode="json")
