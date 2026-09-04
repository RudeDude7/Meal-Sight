"""Typed shapes for the user-intelligence profile: the pydantic schema
layered over user_profile's key/value rows, and the literal types
update_preferences validates against. Also the meal-history and
repetition-check shapes log_meal/rate_meal/get_meal_history/
check_repetition return.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from typing import Any, Literal

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
    # How many real ratings actually fed each cuisine's own score —
    # preference_scores.data_points, never inflated by scoring.py's own
    # smoothing prior (see PREFERENCE_SMOOTHING_PRIOR_WEIGHT). Added
    # alongside cuisine_preferences, not folded into it, specifically so
    # nothing that already reads cuisine_preferences as a plain {cuisine:
    # score} mapping (mealsight.agent.nodes.reason's own prompt builder,
    # for one) needs to change at all.
    cuisine_preference_data_points: dict[str, int]


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


class InteractionRecord(BaseModel):
    """One interaction_history row: every recommendation request and its
    outcome, regardless of whether anything was actually cooked
    (meal_history only ever records a CONFIRMED cook — this is every
    REQUEST, cooked or not). Text only: voice_transcript is the
    transcript text itself, never the audio bytes; ingredients_summary
    is a short text description of what a photo yielded, never the
    image bytes. merged_constraints is the merged request's own
    constraint fields as a plain dict, null when perception never ran
    far enough to produce one at all (e.g. no usable input). recommended
    _recipe_id/_recipe_name are both null on a run that recommended
    nothing — a closest-candidates-not-cookable explanation, or no
    candidates at all."""

    model_config = ConfigDict(frozen=True)

    id: int
    created_at: datetime
    trace_id: str | None
    modalities: list[str]
    text_input: str | None
    voice_transcript: str | None
    ingredients_summary: str | None
    merged_constraints: dict[str, Any] | None
    recommended_recipe_id: str | None
    recommended_recipe_name: str | None
    any_cookable: bool
    top_match_score: float | None
    final_response: str | None


class ContextSignals(BaseModel):
    """What get_context_signals returns: meal_type and
    complexity_suggestion are both derived purely from the clock and the
    calendar (see mealsight.user_intelligence.context's own hour/weekday
    boundary constants); context_notes is what cooking_patterns actually
    says about this day/hour, always at least one string even when
    cooking_patterns has no rows at all yet.

    temperature_f, conditions, and mood_suggestion are the optional
    sixth (weather) signal — see mealsight.utils.weather's own module
    docstring. All three are null together whenever weather data isn't
    available (no API key configured, or the lookup failed) — never
    partially populated, and never a reason for get_context_signals
    itself to fail or for anything downstream to treat a recipe as
    excluded."""

    model_config = ConfigDict(frozen=True)

    meal_type: MealType
    complexity_suggestion: str
    context_notes: list[str]
    temperature_f: float | None = None
    conditions: str | None = None
    mood_suggestion: str | None = None


TasteTimeRange = Literal["this_week", "this_month", "all_time"]


class TasteInsights(BaseModel):
    """What get_taste_insights returns. When sufficient_history is
    False (fewer than settings.min_meals_for_insights meals cooked in
    time_range), every statistic is null and message explains why —
    never a real-looking number computed over a handful of meals.

    protein_variety_score is normalized Shannon entropy (Pielou's
    evenness index) over which protein each cooked meal centered on —
    0.0 means every meal centered on the same one protein, 1.0 means
    every distinct protein cooked appeared equally often. Null when
    sufficient_history is False, or when not one cooked meal in the
    window had an identifiable protein at all (see mealsight.user_
    intelligence.scoring.derive_protein).

    preferred_cook_time_minutes is the MEDIAN cook_time_minutes among
    recipes actually cooked in the window — deliberately not the same
    thing as stated_preferred_cook_time_minutes (the profile's own
    stated preference, included alongside for direct comparison),
    since actual behavior and a stated preference can genuinely
    diverge."""

    model_config = ConfigDict(frozen=True)

    time_range: TasteTimeRange
    sufficient_history: bool
    message: str | None
    total_meals_cooked: int
    most_cooked_cuisine: str | None
    average_rating: float | None
    protein_variety_score: float | None
    cooking_frequency_per_week: float | None
    preferred_cook_time_minutes: float | None
    stated_preferred_cook_time_minutes: int
    suggestions: list[str]
