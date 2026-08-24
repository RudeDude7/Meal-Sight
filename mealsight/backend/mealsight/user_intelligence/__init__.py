"""User Intelligence — plain Python tools over the user_profile and
preference_scores tables: a typed profile schema layered over
user_profile's key/value rows, with additive dietary_restrictions/
disliked_ingredients and replacing scalar fields. All deterministic, no
LLM calls anywhere. No MCP wrapper yet — these are called directly for
now.
"""

from mealsight.user_intelligence.models import (
    ADDITIVE_PREFERENCE_TYPES,
    BudgetSensitivity,
    CookingSkill,
    PreferenceType,
    UserProfile,
)
from mealsight.user_intelligence.preferences import remove_preference, update_preferences
from mealsight.user_intelligence.profile import DEFAULT_PROFILE_VALUES, get_user_profile

__all__ = [
    "ADDITIVE_PREFERENCE_TYPES",
    "DEFAULT_PROFILE_VALUES",
    "BudgetSensitivity",
    "CookingSkill",
    "PreferenceType",
    "UserProfile",
    "get_user_profile",
    "remove_preference",
    "update_preferences",
]
