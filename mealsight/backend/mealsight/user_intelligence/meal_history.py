"""log_meal / rate_meal / get_meal_history — the record of what was
actually cooked, when, and how it was rated. rate_meal (and log_meal,
when a rating is supplied directly) is what actually triggers
mealsight.user_intelligence.scoring.recompute_preference_scores.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from datetime import date as date_
from typing import Any

from mealsight.db import get_recipe_db, get_user_db
from mealsight.db.connection import Database
from mealsight.user_intelligence._datetime_utils import parse_sqlite_timestamp
from mealsight.user_intelligence.context import record_cooking_pattern
from mealsight.user_intelligence.models import MealRecord
from mealsight.user_intelligence.scoring import recompute_preference_scores


def _validate_rating(rating: int | None) -> None:
    if rating is None:
        return
    if not isinstance(rating, int) or isinstance(rating, bool) or not (1 <= rating <= 5):
        raise ValueError(f"rating must be an integer from 1 to 5, or null, got {rating!r}.")


async def _lookup_cook_time_minutes(recipe_id: str | None, recipe_db: Database | None) -> float | None:
    if recipe_id is None:
        return None
    recipe_db = recipe_db or get_recipe_db()
    row = await recipe_db.fetch_one("SELECT cook_time_minutes FROM recipes WHERE id = ?", (recipe_id,))
    return row["cook_time_minutes"] if row is not None else None


def _row_to_meal_record(row: Any) -> MealRecord:
    return MealRecord(
        id=row["id"],
        recipe_id=row["recipe_id"],
        recipe_name=row["recipe_name"],
        cuisine=row["cuisine"],
        meal_type=row["meal_type"],
        date=date_.fromisoformat(row["date"]),
        rating=row["rating"],
        servings_made=row["servings_made"],
        ingredients_used=json.loads(row["ingredients_used"]) if row["ingredients_used"] is not None else None,
        notes=row["notes"],
        cooked_at=parse_sqlite_timestamp(row["cooked_at"]),
    )


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
    user_db: Database | None = None,
    recipe_db: Database | None = None,
) -> MealRecord:
    """Records one cooked meal. rating is optional — a meal is very
    commonly logged the moment it's cooked, rated (or not) some time
    later via rate_meal. If rating IS supplied here, preference scores
    are recomputed immediately, exactly as if rate_meal had been called
    right after.

    Raises ValueError if rating is given and isn't an integer from 1 to
    5.
    """
    _validate_rating(rating)
    user_db = user_db or get_user_db()

    meal_id = await user_db.execute(
        "INSERT INTO meal_history "
        "(recipe_id, recipe_name, cuisine, meal_type, date, rating, servings_made, ingredients_used, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            recipe_id,
            recipe_name,
            cuisine,
            meal_type,
            date.isoformat(),
            rating,
            servings_made,
            json.dumps(ingredients_used) if ingredients_used is not None else None,
            notes,
        ),
    )

    row = await user_db.fetch_one("SELECT * FROM meal_history WHERE id = ?", (meal_id,))
    assert row is not None  # just inserted, in the same connection
    meal = _row_to_meal_record(row)

    cook_time_minutes = await _lookup_cook_time_minutes(recipe_id, recipe_db)
    await record_cooking_pattern(meal.cooked_at, cook_time_minutes, user_db=user_db)

    if rating is not None:
        await recompute_preference_scores(user_db=user_db, recipe_db=recipe_db)

    return meal


async def rate_meal(
    meal_id: int,
    rating: int | None,
    user_db: Database | None = None,
    recipe_db: Database | None = None,
) -> MealRecord:
    """Rates (or re-rates, or — passing rating=None — clears the rating
    of) an already-logged meal, then recomputes cuisine/protein
    preference scores from every currently-rated meal in meal_history.
    See scoring.recompute_preference_scores for why that's a full
    recompute, not an incremental adjustment.

    Raises ValueError if rating isn't an integer from 1 to 5 (or null),
    or if meal_id doesn't match any logged meal.
    """
    _validate_rating(rating)
    user_db = user_db or get_user_db()

    existing = await user_db.fetch_one("SELECT id FROM meal_history WHERE id = ?", (meal_id,))
    if existing is None:
        raise ValueError(f"No meal found with id {meal_id!r}.")

    await user_db.execute("UPDATE meal_history SET rating = ? WHERE id = ?", (rating, meal_id))
    await recompute_preference_scores(user_db=user_db, recipe_db=recipe_db)

    row = await user_db.fetch_one("SELECT * FROM meal_history WHERE id = ?", (meal_id,))
    assert row is not None
    return _row_to_meal_record(row)


async def get_meal_history(
    days_back: int = 14,
    cuisine_filter: str | None = None,
    rating_filter: int | None = None,
    user_db: Database | None = None,
) -> list[MealRecord]:
    """Returns meals cooked in the last days_back days, most recent
    first (by date, then by when it was actually logged). cuisine_filter
    and rating_filter are both plain, optional exact-match filters. An
    empty list, never an error, on a database with no meals logged at
    all yet."""
    user_db = user_db or get_user_db()

    query = "SELECT * FROM meal_history WHERE date >= date('now', ?)"
    params: list[Any] = [f"-{days_back} days"]
    if cuisine_filter is not None:
        query += " AND cuisine = ?"
        params.append(cuisine_filter)
    if rating_filter is not None:
        query += " AND rating = ?"
        params.append(rating_filter)
    query += " ORDER BY date DESC, cooked_at DESC"

    rows = await user_db.fetch_all(query, params)
    return [_row_to_meal_record(row) for row in rows]
