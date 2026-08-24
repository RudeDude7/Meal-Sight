"""Typed shapes for the user-intelligence profile: the pydantic schema
layered over user_profile's key/value rows, and the literal types
update_preferences validates against.
"""

from __future__ import annotations

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
