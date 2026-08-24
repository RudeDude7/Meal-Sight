"""recompute_preference_scores — cuisine and protein preference scores
derived from every rated meal in meal_history, recomputed from scratch
(not incrementally) whenever a rating is written.

A full recompute rather than an incremental update is a deliberate
simplicity choice: an incremental update (adjust the running mean by
one new data point) would need to correctly handle a rating being
*changed* later, not just added — rate_meal can re-rate an already-rated
meal — and getting that subtraction-then-readdition right for a mean
that's already been shrunk toward neutral (below) is exactly the kind
of thing that quietly drifts out of sync with what meal_history actually
contains if any single edge case is missed. A full pass over meal_history
can't drift, by construction, and this table will never be large enough
(one household's cooking history) to make that pass expensive.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from mealsight.db import get_recipe_db, get_user_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.seed.recipe_parsing import PROTEIN_TERMS

# How many "assumed neutral" (score 0.5) pseudo-ratings each dimension
# value's score is shrunk toward before its real ratings are trusted at
# face value: shrunk_score = (raw_mean * n + PRIOR_WEIGHT * 0.5) / (n +
# PRIOR_WEIGHT). Chosen so a single 5-star rating (raw normalized score
# 1.0, n=1) shrinks to (1.0*1 + 3*0.5) / (1+3) = 0.625 — visibly
# positive, but nowhere near "confirmed strong preference" — while ten
# 5-star ratings at the same raw mean shrink only to (1.0*10 + 3*0.5) /
# 13 ≈ 0.885, with the prior's influence fading toward irrelevance as
# real evidence accumulates. 3 is not derived from any data; it's a
# judgment call for "roughly three ratings' worth of default skepticism,"
# small enough that a handful of real ratings quickly dominates it.
PREFERENCE_SMOOTHING_PRIOR_WEIGHT = 3.0
_NEUTRAL_SCORE = 0.5


def _normalize_rating(rating: int) -> float:
    """Maps a 1-5 star rating onto 0.0-1.0."""
    return (rating - 1) / 4


def _shrink_toward_neutral(raw_mean: float, data_points: int) -> float:
    return (raw_mean * data_points + PREFERENCE_SMOOTHING_PRIOR_WEIGHT * _NEUTRAL_SCORE) / (
        data_points + PREFERENCE_SMOOTHING_PRIOR_WEIGHT
    )


def _matches_whole_word(name: str, term: str) -> bool:
    """Whole-word containment, not raw substring containment — the same
    discipline mealsight.pantry.category and mealsight.seed.recipe_
    parsing's own _matches_any_term_whole_word already use, and for the
    identical reason: a raw `term in name` check would let "egg" match
    inside "reggiano"."""
    return re.search(rf"\b{re.escape(term)}\b", name) is not None


def derive_protein(ingredient_names: list[str]) -> str | None:
    """Returns the first PROTEIN_TERMS word found among ingredient_names
    (each run through normalize_ingredient first, so "Chicken Breasts"
    and "chicken breast" both resolve the same way, and a plural term
    like "eggs" naturally never matches since normalization already
    singularized it to "egg") — or None when no ingredient is
    identifiably a protein at all."""
    for name in ingredient_names:
        normalized = normalize_ingredient(name)
        for term in PROTEIN_TERMS:
            if _matches_whole_word(normalized, term):
                return term
    return None


async def load_recipe_ingredient_names(recipe_db: Database, recipe_ids: set[str]) -> dict[str, list[str]]:
    """Batch-loads {recipe_id: [ingredient names]} for every id in
    recipe_ids in one query — the same "load a reference table into a
    plain Python dict once, then use it against data from anywhere"
    pattern mealsight.pantry already established for its own
    cross-database synonym-table dependency. Never a SQL join: recipes.db
    and user_intelligence.db are separate physical files."""
    if not recipe_ids:
        return {}
    placeholders = ",".join("?" for _ in recipe_ids)
    rows = await recipe_db.fetch_all(
        f"SELECT id, ingredients FROM recipes WHERE id IN ({placeholders})", tuple(recipe_ids)
    )
    return {row["id"]: [item["name"] for item in json.loads(row["ingredients"])] for row in rows}


async def _write_dimension_scores(
    user_db: Database, dimension: str, ratings_by_value: Mapping[str, list[float]]
) -> None:
    # Clear this dimension entirely first, so a value that no longer has
    # any rated meals behind it (its one rating got cleared via
    # rate_meal(meal_id, None)) doesn't linger with a stale score.
    await user_db.execute("DELETE FROM preference_scores WHERE dimension = ?", (dimension,))
    for value, ratings in ratings_by_value.items():
        data_points = len(ratings)
        raw_mean = sum(ratings) / data_points
        score = _shrink_toward_neutral(raw_mean, data_points)
        await user_db.execute(
            "INSERT INTO preference_scores (dimension, value, score, data_points, last_updated) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (dimension, value, score, data_points),
        )


async def recompute_preference_scores(
    user_db: Database | None = None, recipe_db: Database | None = None
) -> None:
    """Recomputes both dimension='cuisine' and dimension='protein' rows
    in preference_scores from EVERY currently-rated meal in meal_history.

    cuisine comes straight from meal_history.cuisine (denormalized at
    log_meal time, no recipes.db read needed). protein is derived from
    each rated meal's recipe's ingredients — recipes.db, loaded into
    memory once for every distinct recipe_id involved, never joined in
    SQL — via derive_protein; a rated meal with no recipe_id, or whose
    ingredients don't identifiably contain a protein term, simply
    doesn't contribute to the protein dimension at all.

    Each value's score is the mean of its ratings, normalized 0.0-1.0,
    then shrunk toward 0.5 — see PREFERENCE_SMOOTHING_PRIOR_WEIGHT.
    data_points is always the real number of ratings that went into a
    score, never inflated by the smoothing prior.
    """
    user_db = user_db or get_user_db()
    recipe_db = recipe_db or get_recipe_db()

    rows = await user_db.fetch_all(
        "SELECT recipe_id, cuisine, rating FROM meal_history WHERE rating IS NOT NULL"
    )

    recipe_ids_needed = {row["recipe_id"] for row in rows if row["recipe_id"] is not None}
    ingredients_by_recipe = await load_recipe_ingredient_names(recipe_db, recipe_ids_needed)

    cuisine_ratings: dict[str, list[float]] = {}
    protein_ratings: dict[str, list[float]] = {}

    for row in rows:
        normalized = _normalize_rating(row["rating"])

        if row["cuisine"]:
            cuisine_ratings.setdefault(row["cuisine"], []).append(normalized)

        if row["recipe_id"] is not None:
            protein = derive_protein(ingredients_by_recipe.get(row["recipe_id"], []))
            if protein is not None:
                protein_ratings.setdefault(protein, []).append(normalized)

    await _write_dimension_scores(user_db, "cuisine", cuisine_ratings)
    await _write_dimension_scores(user_db, "protein", protein_ratings)
