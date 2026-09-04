"""get_taste_insights — behavioral analytics over what was actually
cooked: cuisine/protein patterns, cooking frequency, actual (not
stated) preferred cook time, and specific, data-derived suggestions.

Reuses rather than reimplements throughout: derive_protein and
load_recipe_ingredient_names (mealsight.user_intelligence.scoring, the
same functions recompute_preference_scores and check_repetition already
use) for protein derivation; the exact same cross-database "load a
reference table into a plain dict, never a SQL join" pattern those two
modules already established for their own recipes.db reads, extended
here to a THIRD physical database (pantry.db's own waste_log) for the
waste-correlation suggestion.

Deterministic, no LLM calls — every suggestion here is a plain f-string
built from real, queried numbers, never a generated sentence.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import date as date_
from datetime import datetime, timedelta
from math import log
from typing import Any

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db, get_user_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.user_intelligence._datetime_utils import parse_sqlite_timestamp
from mealsight.user_intelligence.models import TasteInsights, TasteTimeRange
from mealsight.user_intelligence.profile import get_user_profile
from mealsight.user_intelligence.scoring import derive_protein, load_recipe_ingredient_names

# "Frequently wasted" reuses settings.waste_insight_threshold directly
# — the exact bar mealsight.pantry.waste already uses to decide an item
# has been thrown out often enough to comment on; there is no reason a
# second, independently-tuned threshold should exist for the same
# underlying question ("has this been wasted enough times to be worth
# mentioning") asked from a different module.
#
# "Rarely cooked with" is this module's own new threshold, since
# nothing existing answers it: at most this many meals in the SAME
# window actually used the ingredient. 1 — not 0 — deliberately: an
# ingredient bought once, used in exactly one meal, and thrown out
# repeatedly afterward is still a genuine "you keep buying this and
# not using it" pattern, not disqualified just because it was tried
# once.
RARELY_COOKED_MAX_MEALS = 1

# A cuisine must account for at least this share of the window's own
# meals before "you've been cooking a lot of X" is worth surfacing as
# its own suggestion — matches repetition.py's own _CUISINE_DOMINANCE_
# THRESHOLD exactly (0.5), a deliberately identical bar: "half the
# window" is the same real-world threshold whether the question is
# "should THIS recipe be flagged as repetitive" or "is this a pattern
# worth mentioning in a summary."
_CUISINE_DOMINANCE_THRESHOLD = 0.5

# Below this, protein_variety_score reads as "lacks variety" in a
# suggestion — a round, defensible middle point on the 0-1 evenness
# scale (see TasteInsights' own docstring for what the score means),
# not benchmark-derived.
_LOW_PROTEIN_VARIETY_THRESHOLD = 0.5

# How much an actual median cook time has to differ from the profile's
# own STATED preference before it's worth a suggestion — a small
# difference (a few minutes) is noise, not a real behavioral signal.
_COOK_TIME_DIVERGENCE_MINUTES = 15


def _period_start(time_range: TasteTimeRange, current_time: datetime) -> datetime:
    """Same boundary shape mealsight.pantry.waste._period_bounds
    already established (Monday-midnight for this_week, the 1st of the
    month for this_month) — reimplemented locally rather than imported,
    since that function is private to a sibling server's own module."""
    if time_range == "this_week":
        return (current_time - timedelta(days=current_time.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if time_range == "this_month":
        return current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return datetime.min


def _protein_variety_score(proteins: list[str]) -> float | None:
    """Normalized Shannon entropy (Pielou's evenness index): H = -sum(p
    * ln p) over each distinct protein's own share of `proteins`,
    divided by ln(N) where N is how many distinct proteins appear at
    all. 0.0 means every meal centered on the same single protein; 1.0
    means every distinct protein appeared equally often. This is
    deliberately NOT a distinct-count — cooking chicken nine times and
    beef once is 2 distinct proteins by a naive count but scores 0.0-
    0.5-ish here (skewed, not actually varied), while five different
    proteins cooked twice each scores close to 1.0. None when no meal
    in the window had an identifiable protein at all."""
    if not proteins:
        return None
    counts = Counter(proteins)
    if len(counts) == 1:
        return 0.0
    total = len(proteins)
    entropy = -sum((count / total) * log(count / total) for count in counts.values())
    max_entropy = log(len(counts))
    return entropy / max_entropy


async def _actual_ingredient_names_by_meal(
    rows: list[Any], recipe_db: Database
) -> list[list[str]]:
    recipe_ids_needed = {row["recipe_id"] for row in rows if row["recipe_id"] is not None}
    ingredients_by_recipe = await load_recipe_ingredient_names(recipe_db, recipe_ids_needed)

    result: list[list[str]] = []
    for row in rows:
        if row["recipe_id"] is not None:
            result.append(ingredients_by_recipe.get(row["recipe_id"], []))
        elif row["ingredients_used"] is not None:
            result.append(list(json.loads(row["ingredients_used"])))
        else:
            result.append([])
    return result


async def _waste_correlation_suggestion(
    pantry_db: Database, all_time_ingredient_lists: list[list[str]]
) -> str | None:
    """Only draws the correlation when BOTH: the ingredient has been
    logged as wasted settings.waste_insight_threshold times or more
    (all-time — the same real bar mealsight.pantry.waste already uses
    to decide something is worth mentioning at all), AND it appears in
    at most RARELY_COOKED_MAX_MEALS of the user's own all-time cooked
    meals. Checked against ALL-TIME cooking history regardless of the
    requested time_range, matching mealsight.pantry.waste's own
    active_insights precedent: a real behavioral pattern like this
    isn't something that should appear or vanish just because a
    narrower window was requested."""
    waste_rows = await pantry_db.fetch_all(
        "SELECT item_name, COUNT(*) as waste_count FROM waste_log GROUP BY item_name"
    )
    frequently_wasted = {
        row["item_name"]: row["waste_count"]
        for row in waste_rows
        if row["waste_count"] >= settings.waste_insight_threshold
    }
    if not frequently_wasted:
        return None

    cooked_counts: Counter[str] = Counter()
    for ingredient_names in all_time_ingredient_lists:
        for name in ingredient_names:
            cooked_counts[normalize_ingredient(name)] += 1

    for item_name, waste_count in sorted(frequently_wasted.items(), key=lambda kv: -kv[1]):
        cooked_count = cooked_counts.get(normalize_ingredient(item_name), 0)
        if cooked_count <= RARELY_COOKED_MAX_MEALS:
            times = "time" if waste_count == 1 else "times"
            meal_word = "meal" if cooked_count == 1 else "meals"
            return (
                f"You've thrown away {item_name} {waste_count} {times} but only cooked with it "
                f"in {cooked_count} {meal_word} — consider buying it only when a specific recipe "
                "calls for it."
            )
    return None


def _cuisine_dominance_suggestion(
    cuisine_counts: Counter[str],
    total_meals: int,
    cuisine_ratings: dict[str, list[int]],
    cuisine_last_cooked: dict[str, datetime],
    now: datetime,
) -> str | None:
    if not cuisine_counts:
        return None
    dominant_cuisine, dominant_count = cuisine_counts.most_common(1)[0]
    if dominant_count / total_meals < _CUISINE_DOMINANCE_THRESHOLD:
        return None

    # Look for a real alternative: a DIFFERENT cuisine, rated, that
    # hasn't been cooked recently — the exact worked example's own
    # shape ("your Mexican recipes rate 4.5 on average and you haven't
    # made one in three weeks").
    best_alternative: tuple[str, float, int] | None = None
    for cuisine, ratings in cuisine_ratings.items():
        if cuisine == dominant_cuisine or not ratings:
            continue
        last_cooked = cuisine_last_cooked.get(cuisine)
        days_since = (now - last_cooked).days if last_cooked else 999
        average = sum(ratings) / len(ratings)
        if best_alternative is None or average > best_alternative[1]:
            best_alternative = (cuisine, average, days_since)

    base = f"You've cooked {dominant_cuisine} {dominant_count} of your last {total_meals} meals"
    if best_alternative is not None:
        alt_cuisine, alt_average, alt_days_since = best_alternative
        weeks_since = alt_days_since // 7
        recency = (
            f"you haven't made one in {weeks_since} week{'s' if weeks_since != 1 else ''}"
            if weeks_since >= 1
            else "you made one recently"
        )
        return (
            f"{base} — your {alt_cuisine} recipes rate {alt_average:.1f} on average and {recency}."
        )
    return f"{base} — consider mixing in a different cuisine."


def _protein_variety_suggestion(proteins: list[str], score: float | None) -> str | None:
    if score is None or score >= _LOW_PROTEIN_VARIETY_THRESHOLD or not proteins:
        return None
    dominant_protein, dominant_count = Counter(proteins).most_common(1)[0]
    share_pct = round(100 * dominant_count / len(proteins))
    return (
        f"{dominant_protein} made up {share_pct}% of your protein-identifiable meals "
        f"({dominant_count} of {len(proteins)}) — worth branching out for variety."
    )


def _cook_time_suggestion(actual_median: float | None, stated: int) -> str | None:
    if actual_median is None:
        return None
    if abs(actual_median - stated) < _COOK_TIME_DIVERGENCE_MINUTES:
        return None
    direction = "longer" if actual_median > stated else "shorter"
    return (
        f"You actually cook meals averaging {actual_median:.0f} minutes, {direction} than the "
        f"{stated}-minute preference on your profile — worth updating it to match."
    )


async def get_taste_insights(
    time_range: TasteTimeRange,
    current_time: datetime | None = None,
    user_db: Database | None = None,
    recipe_db: Database | None = None,
    pantry_db: Database | None = None,
) -> TasteInsights:
    """Behavioral analytics over meal_history for time_range
    ("this_week", "this_month", "all_time").

    Below settings.min_meals_for_insights cooked meals in the window,
    every statistic is null and message says so plainly — never
    computed over a handful of data points. Otherwise: total meals
    cooked, most-cooked cuisine, average rating, protein_variety_score
    (see that field's own docstring on TasteInsights), cooking_
    frequency_per_week, the ACTUAL median cook time of recipes cooked
    (vs. the profile's own stated preference), and 0 or more specific,
    data-derived suggestions (cuisine dominance vs. a real rated
    alternative, low protein variety, a stated-vs-actual cook-time
    mismatch, and a waste/cooking correlation when the data actually
    supports one — see _waste_correlation_suggestion).
    """
    user_db = user_db or get_user_db()
    recipe_db = recipe_db or get_recipe_db()
    pantry_db = pantry_db or get_pantry_db()
    now = current_time or datetime.now()

    window_start = _period_start(time_range, now)
    rows = await user_db.fetch_all(
        "SELECT recipe_id, cuisine, rating, ingredients_used, date, cooked_at FROM meal_history "
        "WHERE cooked_at >= ?",
        (window_start.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    total_meals = len(rows)

    if total_meals < settings.min_meals_for_insights:
        profile = await get_user_profile(user_db)
        return TasteInsights(
            time_range=time_range,
            sufficient_history=False,
            message=(
                f"Only {total_meals} meal(s) logged for {time_range.replace('_', ' ')} — "
                f"at least {settings.min_meals_for_insights} are needed before these statistics "
                "mean anything."
            ),
            total_meals_cooked=total_meals,
            most_cooked_cuisine=None,
            average_rating=None,
            protein_variety_score=None,
            cooking_frequency_per_week=None,
            preferred_cook_time_minutes=None,
            stated_preferred_cook_time_minutes=profile.preferred_cook_time_minutes,
            suggestions=[],
        )

    cuisine_counts: Counter[str] = Counter(row["cuisine"] for row in rows if row["cuisine"])
    most_cooked_cuisine = cuisine_counts.most_common(1)[0][0] if cuisine_counts else None

    ratings = [row["rating"] for row in rows if row["rating"] is not None]
    average_rating = sum(ratings) / len(ratings) if ratings else None

    ingredient_lists = await _actual_ingredient_names_by_meal(rows, recipe_db)
    proteins = [p for names in ingredient_lists for p in [derive_protein(names)] if p is not None]
    protein_variety_score = _protein_variety_score(proteins)

    recipe_ids_needed = {row["recipe_id"] for row in rows if row["recipe_id"] is not None}
    cook_times: dict[str, int | None] = {}
    if recipe_ids_needed:
        placeholders = ",".join("?" for _ in recipe_ids_needed)
        cook_time_rows = await recipe_db.fetch_all(
            f"SELECT id, cook_time_minutes FROM recipes WHERE id IN ({placeholders})",
            tuple(recipe_ids_needed),
        )
        cook_times = {row["id"]: row["cook_time_minutes"] for row in cook_time_rows}
    actual_cook_times: list[int] = []
    for row in rows:
        cook_time = cook_times.get(row["recipe_id"]) if row["recipe_id"] is not None else None
        if cook_time is not None:
            actual_cook_times.append(cook_time)
    preferred_cook_time_minutes = (
        statistics.median(actual_cook_times) if actual_cook_times else None
    )

    if time_range == "all_time":
        earliest_date = min(date_.fromisoformat(row["date"]) for row in rows)
        days_elapsed = max((now.date() - earliest_date).days, 1)
    else:
        days_elapsed = max((now - window_start).days, 1)
    cooking_frequency_per_week = total_meals / (days_elapsed / 7)

    cuisine_ratings: dict[str, list[int]] = {}
    cuisine_last_cooked: dict[str, datetime] = {}
    for row in rows:
        if row["cuisine"] and row["rating"] is not None:
            cuisine_ratings.setdefault(row["cuisine"], []).append(row["rating"])
        if row["cuisine"]:
            cooked_at = parse_sqlite_timestamp(row["cooked_at"])
            existing = cuisine_last_cooked.get(row["cuisine"])
            if existing is None or cooked_at > existing:
                cuisine_last_cooked[row["cuisine"]] = cooked_at

    profile = await get_user_profile(user_db)

    all_time_rows = (
        rows
        if time_range == "all_time"
        else await user_db.fetch_all(
            "SELECT recipe_id, ingredients_used FROM meal_history"
        )
    )
    all_time_ingredient_lists = (
        ingredient_lists
        if time_range == "all_time"
        else await _actual_ingredient_names_by_meal(all_time_rows, recipe_db)
    )

    suggestions: list[str] = []
    for suggestion in (
        _cuisine_dominance_suggestion(cuisine_counts, total_meals, cuisine_ratings, cuisine_last_cooked, now),
        _protein_variety_suggestion(proteins, protein_variety_score),
        _cook_time_suggestion(preferred_cook_time_minutes, profile.preferred_cook_time_minutes),
        await _waste_correlation_suggestion(pantry_db, all_time_ingredient_lists),
    ):
        if suggestion is not None:
            suggestions.append(suggestion)

    return TasteInsights(
        time_range=time_range,
        sufficient_history=True,
        message=None,
        total_meals_cooked=total_meals,
        most_cooked_cuisine=most_cooked_cuisine,
        average_rating=average_rating,
        protein_variety_score=protein_variety_score,
        cooking_frequency_per_week=cooking_frequency_per_week,
        preferred_cook_time_minutes=preferred_cook_time_minutes,
        stated_preferred_cook_time_minutes=profile.preferred_cook_time_minutes,
        suggestions=suggestions,
    )
