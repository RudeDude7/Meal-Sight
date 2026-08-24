"""The user-intelligence MCP server: a thin FastMCP transport shell over
mealsight.user_intelligence. Every tool here validates its own input,
calls straight into an existing, independently-tested function, and
serializes the result (mealsight.mcp_servers.user_intelligence.
serialization) — no profile, scoring, repetition, or context logic is
reimplemented in this file. If a rule about what counts as a repeated
meal or a typical cooking hour ever needs to change, it changes in the
underlying module, not here.

Deterministic, no LLM calls anywhere in this module either.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from typing import Any

from fastmcp import FastMCP

from mealsight.db import get_user_db
from mealsight.mcp_servers.user_intelligence.serialization import (
    context_signals_to_dict,
    internal_error,
    meal_history_to_dict,
    meal_record_to_dict,
    not_found_error,
    repetition_check_to_dict,
    user_profile_to_dict,
    validation_error,
)
from mealsight.user_intelligence import check_repetition as _check_repetition
from mealsight.user_intelligence import get_context_signals as _get_context_signals
from mealsight.user_intelligence import get_meal_history as _get_meal_history
from mealsight.user_intelligence import get_user_profile as _get_user_profile
from mealsight.user_intelligence import log_meal as _log_meal
from mealsight.user_intelligence import update_preferences as _update_preferences
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.user_intelligence")

mcp: FastMCP[Any] = FastMCP("user-intelligence")


@mcp.tool
async def get_user_profile() -> dict[str, Any]:
    """Reads the full user profile: dietary_restrictions,
    disliked_ingredients, preferred_cook_time_minutes, household_size,
    protein_preference, cooking_skill, budget_sensitivity, and
    cuisine_preferences (a {cuisine: score} mapping, 0.0-1.0, learned
    from rated meals — empty until at least one meal has been rated).
    Call this before recommending anything, so restrictions/dislikes can
    rule things out and cuisine_preferences can rank what's left.

    Every field has a sensible default and this always succeeds, even on
    a completely fresh profile that's never been touched.
    """
    try:
        db = get_user_db()
        result = await _get_user_profile(user_db=db)
        return user_profile_to_dict(result)
    except Exception:
        logger.error("get_user_profile_failed", exc_info=True)
        return internal_error()


@mcp.tool
async def update_preferences(preference_type: str, value: Any) -> dict[str, Any]:
    """Writes one preference and returns the full, updated profile.

    preference_type must be one of: "dietary_restrictions",
    "disliked_ingredients" (both ADDITIVE — value may be a string or a
    list of strings, appended and deduplicated, never replacing what's
    already stored), "household_size", "preferred_cook_time_minutes"
    (both positive integers), "cooking_skill" ("beginner", "intermediate",
    or "advanced"), "budget_sensitivity" ("budget", "moderate", or
    "flexible"), or "protein_preference" (any string, or null to clear
    it) — all five of these REPLACE the existing value.

    Returns a structured {"error": "validation_error", ...} naming
    preference_type and the specific problem (an unrecognized field name,
    or a value that fails that field's own range/enum check) rather than
    raising.
    """
    try:
        db = get_user_db()
        result = await _update_preferences(preference_type, value, user_db=db)
        return user_profile_to_dict(result)
    except ValueError as exc:
        return validation_error(preference_type, str(exc))
    except Exception:
        logger.error("update_preferences_failed", exc_info=True, preference_type=preference_type)
        return internal_error()


@mcp.tool
async def log_meal(
    recipe_id: str | None,
    recipe_name: str,
    cuisine: str | None,
    meal_type: str | None,
    date: date_,
    rating: int | None = None,
    servings_made: int | None = None,
    ingredients_used: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Records one cooked meal.

    IMPORTANT: call this only AFTER cooking has actually been confirmed
    as having happened — never when a recipe is merely recommended or
    planned. Calling this for a recipe that hasn't actually been cooked
    yet would incorrectly inflate meal_history and skew every downstream
    signal (cuisine_preferences, check_repetition, get_context_signals'
    own behavioral notes) that reads from it.

    rating is optional — a meal is very commonly logged the moment it's
    cooked and rated (or not) later; there is no separate rate_meal tool
    on this server yet, so pass rating here directly whenever it's
    already known. Supplying rating here immediately updates
    cuisine_preferences and protein preference scores.

    Returns the full recorded meal: {"id", "recipe_id", "recipe_name",
    "cuisine", "meal_type", "date", "rating", "servings_made",
    "ingredients_used", "notes", "cooked_at"}.

    Returns a structured {"error": "validation_error", ...} naming
    "rating" if it's given and isn't an integer from 1 to 5.
    """
    try:
        db = get_user_db()
        result = await _log_meal(
            recipe_id,
            recipe_name,
            cuisine,
            meal_type,
            date,
            rating=rating,
            servings_made=servings_made,
            ingredients_used=ingredients_used,
            notes=notes,
            user_db=db,
        )
        return meal_record_to_dict(result)
    except ValueError as exc:
        return validation_error("rating", str(exc))
    except Exception:
        logger.error("log_meal_failed", exc_info=True, recipe_name=recipe_name)
        return internal_error()


@mcp.tool
async def get_meal_history(
    days_back: int = 14,
    cuisine_filter: str | None = None,
    rating_filter: int | None = None,
) -> dict[str, Any]:
    """Returns meals cooked in the last days_back days, most recent
    first. cuisine_filter and rating_filter are both plain, optional
    exact-match filters.

    Returns {"meals": [{"id", "recipe_id", "recipe_name", "cuisine",
    "meal_type", "date", "rating", "servings_made", "ingredients_used",
    "notes", "cooked_at"}, ...], "count": int}. An empty list, not an
    error, when nothing's been logged (yet, or in that window).
    """
    try:
        db = get_user_db()
        result = await _get_meal_history(
            days_back=days_back, cuisine_filter=cuisine_filter, rating_filter=rating_filter, user_db=db
        )
        return meal_history_to_dict(result)
    except Exception:
        logger.error("get_meal_history_failed", exc_info=True, days_back=days_back)
        return internal_error()


@mcp.tool
async def check_repetition(recipe_id: str, check_window_days: int | None = None) -> dict[str, Any]:
    """Checks whether recommending recipe_id right now would repeat
    something too recent — an exact repeat of this recipe, the same
    protein appearing too often, or the same cuisine dominating the
    check window (in that priority order; see recommendation/reason for
    which one actually fired).

    IMPORTANT: recommendation is a SIGNAL TO WEIGH, not a hard veto. Even
    "too_repetitive" is information for a caller to factor in alongside
    everything else it knows (an explicit request to repeat a favorite,
    for instance) — never treat this tool's output as an automatic
    block on recommending recipe_id.

    check_window_days defaults to the server's configured repetition
    window when omitted.

    Returns {"repetition_score" (0.0-1.0), "reason", "recommendation"
    ("acceptable" | "suggest_alternative" | "too_repetitive"),
    "last_cooked" (the most recent date this exact recipe was logged,
    null if never)}.

    Returns a structured {"error": "not_found", ...} result, not an
    exception, if recipe_id doesn't exist.
    """
    try:
        db = get_user_db()
        result = await _check_repetition(recipe_id, check_window_days=check_window_days, user_db=db)
        return repetition_check_to_dict(result)
    except ValueError:
        return not_found_error("recipe", recipe_id)
    except Exception:
        logger.error("check_repetition_failed", exc_info=True, recipe_id=recipe_id)
        return internal_error()


@mcp.tool
async def get_context_signals(
    current_time: datetime | None = None, day_of_week: int | None = None
) -> dict[str, Any]:
    """Returns situational hints for right now (or for a given
    current_time/day_of_week, to check a different moment): what
    meal_type this hour usually is, a plain-language complexity_
    suggestion for today's day of week (SUGGESTION only, never a hard
    filter — Friday through Sunday leaves room for something more
    elaborate, Monday through Thursday favors something quick), and
    context_notes — whether the user actually has a track record of
    cooking around this day/hour, read from logged history.

    Deliberately has no weather signal at all — there is no weather data
    anywhere in this system.

    current_time and day_of_week both default to the real current
    moment when omitted; day_of_week (Monday=0 ... Sunday=6) can be
    overridden independently of current_time.

    Returns {"meal_type" ("breakfast"|"lunch"|"dinner"|"snack"),
    "complexity_suggestion", "context_notes" (always at least one
    string, even with zero cooking history logged)}.
    """
    try:
        db = get_user_db()
        result = await _get_context_signals(
            current_time=current_time, day_of_week=day_of_week, user_db=db
        )
        return context_signals_to_dict(result)
    except Exception:
        logger.error("get_context_signals_failed", exc_info=True)
        return internal_error()
