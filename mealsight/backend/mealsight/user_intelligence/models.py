"""Typed shapes for the user-intelligence profile: the pydantic schema
layered over user_profile's key/value rows, and the literal types
update_preferences validates against. Also the meal-history and
repetition-check shapes log_meal/rate_meal/get_meal_history/
check_repetition return.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CookingSkill = Literal["beginner", "intermediate", "advanced"]
BudgetSensitivity = Literal["budget", "moderate", "flexible"]

PreferenceType = Literal[
    "dietary_restrictions",
    "disliked_ingredients",
    "preferred_cook_time_minutes",
    "household_size",
    "protein_preference",
    "cooking_skill",
    "budget_sensitivity",
]

# The only two fields update_preferences appends to rather than replaces
# — everything else in PreferenceType is scalar.
ADDITIVE_PREFERENCE_TYPES: frozenset[str] = frozenset({"dietary_restrictions", "disliked_ingredients"})


class UserProfile(BaseModel):
    """The full user profile: known fields layered over user_profile's
    key/value rows, with sensible defaults for anything never set.
    cuisine_preferences is computed live from preference_scores
    (dimension='cuisine') rather than stored under a user_profile key —
    it's never written through update_preferences, since populating it
    is whatever later phase actually rates cuisines' job, not this
    module's."""

    model_config = ConfigDict(frozen=True)

    dietary_restrictions: list[str]
    disliked_ingredients: list[str]
    preferred_cook_time_minutes: int
    household_size: int
    protein_preference: str | None
    cooking_skill: CookingSkill
    budget_sensitivity: BudgetSensitivity
    cuisine_preferences: dict[str, float]


class MealRecord(BaseModel):
    """One meal_history row: what was cooked, when, and how it was
    rated. rating is None for a meal logged but not yet rated —
    rate_meal is the separate call that fills it in later."""

    model_config = ConfigDict(frozen=True)

    id: int
    recipe_id: str | None
    recipe_name: str
    cuisine: str | None
    meal_type: str | None
    date: date_
    rating: int | None
    servings_made: int | None
    ingredients_used: list[str] | None
    notes: str | None
    cooked_at: datetime


RepetitionRecommendation = Literal["acceptable", "suggest_alternative", "too_repetitive"]


class RepetitionCheck(BaseModel):
    """What check_repetition returns for one candidate recipe:
    repetition_score climbs with how strong the repetition signal is
    (0.0 none, 1.0 an exact repeat within the window), reason is a
    human-readable explanation of whichever signal actually fired, and
    last_cooked is the most recent date this exact recipe was ever
    logged — independent of the check window, None if it's never been
    cooked at all."""

    model_config = ConfigDict(frozen=True)

    repetition_score: float
    reason: str
    recommendation: RepetitionRecommendation
    last_cooked: date_ | None


MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class ContextSignals(BaseModel):
    """What get_context_signals returns: meal_type and
    complexity_suggestion are both derived purely from the clock and the
    calendar (see mealsight.user_intelligence.context's own hour/weekday
    boundary constants); context_notes is what cooking_patterns actually
    says about this day/hour, always at least one string even when
    cooking_patterns has no rows at all yet."""

    model_config = ConfigDict(frozen=True)

    meal_type: MealType
    complexity_suggestion: str
    context_notes: list[str]
