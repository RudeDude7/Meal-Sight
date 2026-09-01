"""get_user_profile — reads the user_profile key/value table back into a
typed UserProfile, filling in sensible defaults for anything never set,
and folds in cuisine_preferences computed live from preference_scores.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from typing import Any

from mealsight.db import get_user_db
from mealsight.db.connection import Database
from mealsight.user_intelligence.models import UserProfile

# What get_user_profile returns for any field never written through
# update_preferences — chosen so a completely fresh database still
# produces a profile an agent can act on immediately, not one full of
# nulls it has to special-case.
DEFAULT_PROFILE_VALUES: dict[str, Any] = {
    "dietary_restrictions": [],
    "disliked_ingredients": [],
    "preferred_cook_time_minutes": 30,
    "household_size": 1,
    "protein_preference": None,
    "cooking_skill": "intermediate",
    "budget_sensitivity": "moderate",
}


async def _read_stored_values(user_db: Database) -> dict[str, Any]:
    rows = await user_db.fetch_all("SELECT key, value FROM user_profile")
    return {row["key"]: json.loads(row["value"]) for row in rows}


async def _read_cuisine_preferences(user_db: Database) -> tuple[dict[str, float], dict[str, int]]:
    rows = await user_db.fetch_all(
        "SELECT value, score, data_points FROM preference_scores "
        "WHERE dimension = 'cuisine' ORDER BY score DESC, value"
    )
    scores = {row["value"]: row["score"] for row in rows}
    data_points = {row["value"]: row["data_points"] for row in rows}
    return scores, data_points


async def get_user_profile(user_db: Database | None = None) -> UserProfile:
    """Returns the full user profile, usable on a completely fresh
    database: any field never written through update_preferences comes
    back as DEFAULT_PROFILE_VALUES' default rather than raising or
    coming back null.

    cuisine_preferences is a cuisine -> score mapping read live from
    preference_scores (dimension='cuisine'), sorted highest-scored
    first — an empty mapping, not an error, when nothing has been rated
    yet. cuisine_preference_data_points is the real ratings-count behind
    each of those scores, from the same table's own data_points column.
    """
    user_db = user_db or get_user_db()
    stored = await _read_stored_values(user_db)
    values = {**DEFAULT_PROFILE_VALUES, **stored}
    cuisine_preferences, cuisine_preference_data_points = await _read_cuisine_preferences(user_db)
    return UserProfile(
        **values,
        cuisine_preferences=cuisine_preferences,
        cuisine_preference_data_points=cuisine_preference_data_points,
    )
