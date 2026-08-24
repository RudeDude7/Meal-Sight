"""User Intelligence — plain Python tools over the user_profile and
preference_scores tables: a typed profile schema layered over
user_profile's key/value rows, with additive dietary_restrictions/
disliked_ingredients and replacing scalar fields. All deterministic, no
LLM calls anywhere. No MCP wrapper yet — these are called directly for
now.
"""

from mealsight.user_intelligence.context import get_context_signals, record_cooking_pattern
from mealsight.user_intelligence.meal_history import get_meal_history, log_meal, rate_meal
from mealsight.user_intelligence.models import (
    ADDITIVE_PREFERENCE_TYPES,
    BudgetSensitivity,
    ContextSignals,
    CookingSkill,
    MealRecord,
    MealType,
    PreferenceType,
    RepetitionCheck,
    RepetitionRecommendation,
    UserProfile,
)
from mealsight.user_intelligence.preferences import remove_preference, update_preferences
from mealsight.user_intelligence.profile import DEFAULT_PROFILE_VALUES, get_user_profile
from mealsight.user_intelligence.repetition import check_repetition
from mealsight.user_intelligence.scoring import (
    PREFERENCE_SMOOTHING_PRIOR_WEIGHT,
    recompute_preference_scores,
)

__all__ = [
    "ADDITIVE_PREFERENCE_TYPES",
    "DEFAULT_PROFILE_VALUES",
    "PREFERENCE_SMOOTHING_PRIOR_WEIGHT",
    "BudgetSensitivity",
    "ContextSignals",
    "CookingSkill",
    "MealRecord",
    "MealType",
    "PreferenceType",
    "RepetitionCheck",
    "RepetitionRecommendation",
    "UserProfile",
    "check_repetition",
    "get_context_signals",
    "get_meal_history",
    "get_user_profile",
    "log_meal",
    "rate_meal",
    "recompute_preference_scores",
    "record_cooking_pattern",
    "remove_preference",
    "update_preferences",
]
