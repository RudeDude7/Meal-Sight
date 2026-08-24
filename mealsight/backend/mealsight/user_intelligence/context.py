"""get_context_signals / record_cooking_pattern — turns wall-clock time
and observed cooking history into a small set of situational hints for
an agent deciding what to suggest right now: what meal_type this hour
usually is, how elaborate a recipe today's day of week can typically
support, and whether the user actually has a track record of cooking
at this specific day/hour at all.

Weather is deliberately out of scope: no weather API exists anywhere in
this project (mealsight.config.settings even carries an explicitly
deferred openweather_api_key field for exactly this reason — see that
module's own comment), and this module does not add one. Every signal
here comes from the clock and from cooking_patterns, nothing external.

Deterministic, no LLM calls.
"""

from __future__ import annotations

from datetime import datetime

from mealsight.db import get_user_db
from mealsight.db.connection import Database
from mealsight.user_intelligence.models import ContextSignals, MealType

# Hour boundaries for meal_type, each [start, end) in 24-hour local
# time, chosen to cover the full day with no gaps: anything not
# breakfast, lunch, or dinner is "snack" by definition here — both the
# mid-afternoon lull (15:00-16:59) and everything from after dinner
# through early morning (21:00-4:59).
_BREAKFAST_START_HOUR = 5
_LUNCH_START_HOUR = 11
_AFTERNOON_SNACK_START_HOUR = 15
_DINNER_START_HOUR = 17
_EVENING_SNACK_START_HOUR = 21

# Python's date/datetime.weekday() convention: Monday=0 ... Sunday=6.
# Used consistently for day_of_week everywhere in this module and for
# what's actually stored in cooking_patterns' own rows.
_ELABORATE_WEEKDAYS = frozenset({4, 5, 6})  # Friday, Saturday, Sunday

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _meal_type_from_hour(hour: int) -> MealType:
    if _BREAKFAST_START_HOUR <= hour < _LUNCH_START_HOUR:
        return "breakfast"
    if _LUNCH_START_HOUR <= hour < _AFTERNOON_SNACK_START_HOUR:
        return "lunch"
    if _DINNER_START_HOUR <= hour < _EVENING_SNACK_START_HOUR:
        return "dinner"
    return "snack"  # 15:00-16:59, or 21:00-4:59


def _complexity_suggestion(day_of_week: int) -> str:
    day_name = _DAY_NAMES[day_of_week]
    if day_of_week in _ELABORATE_WEEKDAYS:
        return f"{day_name} — there's room for a more elaborate recipe if you want one."
    return f"{day_name} — a weeknight; favor something quick."


async def _behavioral_note(user_db: Database, day_of_week: int, hour_of_day: int) -> str:
    row = await user_db.fetch_one(
        "SELECT cook_count, average_cook_time_minutes FROM cooking_patterns "
        "WHERE day_of_week = ? AND hour_of_day = ?",
        (day_of_week, hour_of_day),
    )
    day_name = _DAY_NAMES[day_of_week]
    if row is None or row["cook_count"] == 0:
        return f"No cooking history recorded for {day_name} around this hour yet."

    cook_count = row["cook_count"]
    times = "time" if cook_count == 1 else "times"
    if row["average_cook_time_minutes"] is not None:
        return (
            f"You've cooked around this time on {day_name}s {cook_count} {times} before, "
            f"averaging {row['average_cook_time_minutes']:.0f} minutes."
        )
    return f"You've cooked around this time on {day_name}s {cook_count} {times} before."


async def get_context_signals(
    current_time: datetime | None = None,
    day_of_week: int | None = None,
    user_db: Database | None = None,
) -> ContextSignals:
    """Returns three situational hints for right now (or for a given
    current_time/day_of_week, to check a different moment):

    meal_type: "breakfast", "lunch", "dinner", or "snack", from
    current_time's hour alone.

    complexity_suggestion: a plain-language SUGGESTION, not a hard
    filter — Friday through Sunday says there's room for something more
    elaborate, Monday through Thursday suggests favoring something
    quick. A caller is free to override this for a specific request.

    context_notes: behavioral observations read from cooking_patterns —
    whether the user has actually cooked around this day/hour before,
    and if so, how often and roughly how long it takes. Always at least
    one note, even on a completely empty cooking_patterns table (a
    plain "no history yet" note, never an empty list or an error).

    current_time defaults to right now; day_of_week defaults to
    current_time's own weekday (Monday=0 ... Sunday=6) but can be
    overridden independently of it — current_time still supplies the
    hour used for meal_type and the behavioral lookup either way.
    """
    user_db = user_db or get_user_db()
    current_time = current_time or datetime.now()
    resolved_day_of_week = day_of_week if day_of_week is not None else current_time.weekday()

    meal_type = _meal_type_from_hour(current_time.hour)
    complexity_suggestion = _complexity_suggestion(resolved_day_of_week)
    behavioral_note = await _behavioral_note(user_db, resolved_day_of_week, current_time.hour)

    return ContextSignals(
        meal_type=meal_type,
        complexity_suggestion=complexity_suggestion,
        context_notes=[behavioral_note],
    )


async def record_cooking_pattern(
    cooked_at: datetime, cook_time_minutes: float | None, user_db: Database | None = None
) -> None:
    """Updates the cooking_patterns cell for cooked_at's own day_of_week
    and hour_of_day: increments cook_count always, and folds
    cook_time_minutes into a running average when it's actually known.

    A manually-logged meal with no recipe_id, or one whose recipe has no
    recorded cook_time_minutes, simply has no duration to contribute —
    cook_count alone still records that a cooking event happened at this
    day/hour, which is what get_context_signals' behavioral note reads
    even when average_cook_time_minutes stays null.

    The running average is a plain weighted mean against cook_count
    itself. cooking_patterns has no separate column tracking how many of
    its cook_count events actually had a known duration, so this is a
    deliberate approximation — every prior cook_count is assumed to have
    contributed to the existing average once — good enough for a rough
    "about how long this usually takes" signal, not meant to be exact.
    """
    user_db = user_db or get_user_db()
    day_of_week = cooked_at.weekday()
    hour_of_day = cooked_at.hour

    existing = await user_db.fetch_one(
        "SELECT cook_count, average_cook_time_minutes FROM cooking_patterns "
        "WHERE day_of_week = ? AND hour_of_day = ?",
        (day_of_week, hour_of_day),
    )

    if existing is None:
        await user_db.execute(
            "INSERT INTO cooking_patterns "
            "(day_of_week, hour_of_day, cook_count, average_cook_time_minutes, last_updated) "
            "VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)",
            (day_of_week, hour_of_day, cook_time_minutes),
        )
        return

    new_count = existing["cook_count"] + 1
    if cook_time_minutes is None:
        new_average = existing["average_cook_time_minutes"]
    elif existing["average_cook_time_minutes"] is None:
        new_average = cook_time_minutes
    else:
        new_average = (
            existing["average_cook_time_minutes"] * existing["cook_count"] + cook_time_minutes
        ) / new_count

    await user_db.execute(
        "UPDATE cooking_patterns SET cook_count = ?, average_cook_time_minutes = ?, "
        "last_updated = CURRENT_TIMESTAMP WHERE day_of_week = ? AND hour_of_day = ?",
        (new_count, new_average, day_of_week, hour_of_day),
    )
