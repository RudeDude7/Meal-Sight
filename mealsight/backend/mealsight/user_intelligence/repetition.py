"""check_repetition — three-level signal for whether a specific recipe
would be too repetitive to recommend right now: an exact repeat within
the window (strongest), the same protein appearing too often, or the
same cuisine dominating the window.

Reads the candidate recipe's own cuisine and ingredients from
recipes.db — a real cross-database read, loaded into memory and never
joined in SQL, the same pattern mealsight.pantry and mealsight.user_
intelligence.scoring already established for their own recipes.db
dependencies.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from datetime import date as date_

from mealsight.config.settings import settings
from mealsight.db import get_recipe_db, get_user_db
from mealsight.db.connection import Database
from mealsight.user_intelligence.models import RepetitionCheck
from mealsight.user_intelligence.scoring import derive_protein, load_recipe_ingredient_names

# A cuisine must account for at least this fraction of the window's
# meals with a known cuisine (and the window must have at least two such
# meals) before it's flagged as the reason to suggest something
# different — a single meal in the window would otherwise always look
# like "100% of the window is this cuisine," which isn't a meaningful
# repetition signal at all.
_CUISINE_DOMINANCE_THRESHOLD = 0.5
_MIN_WINDOW_MEALS_FOR_CUISINE_CHECK = 2

_EXACT_REPEAT_SCORE = 1.0
_PROTEIN_REPETITION_SCORE = 0.7
_CUISINE_DOMINANCE_SCORE = 0.5
_NO_REPETITION_SCORE = 0.0


async def _meal_ingredient_names(
    row_recipe_id: str | None,
    row_ingredients_used: str | None,
    ingredients_by_recipe: dict[str, list[str]],
) -> list[str]:
    if row_recipe_id is not None:
        return ingredients_by_recipe.get(row_recipe_id, [])
    if row_ingredients_used is not None:
        return list(json.loads(row_ingredients_used))
    return []


async def check_repetition(
    recipe_id: str,
    check_window_days: int | None = None,
    user_db: Database | None = None,
    recipe_db: Database | None = None,
) -> RepetitionCheck:
    """Checks whether recommending recipe_id right now would be
    repetitive, at three levels, checked in order — the first one that
    fires wins:

      1. exact repeat: this exact recipe was already cooked within the
         window. repetition_score 1.0, recommendation "too_repetitive".
      2. protein repetition: this recipe's own dominant protein (the
         first mealsight.seed.recipe_parsing.PROTEIN_TERMS word found
         among its ingredients) has already appeared in more than
         settings.max_same_protein_per_week other meals in the window.
         repetition_score 0.7, recommendation "suggest_alternative".
      3. cuisine dominance: this recipe's cuisine already accounts for
         at least half of the window's cuisine-known meals (and the
         window has at least two of them). repetition_score 0.5,
         recommendation "suggest_alternative".

    A recipe that trips none of the three gets repetition_score 0.0 and
    recommendation "acceptable" — including a recipe that's never been
    cooked at all, which also always has last_cooked=None.

    last_cooked is the most recent date this exact recipe was ever
    logged, independent of check_window_days — a recipe cooked long
    before the window can still report a real last_cooked date even
    though it doesn't trip the exact-repeat check.

    check_window_days defaults to settings.repetition_window_days.

    Raises ValueError if recipe_id doesn't match any recipe in
    recipes.db.
    """
    user_db = user_db or get_user_db()
    recipe_db = recipe_db or get_recipe_db()
    window_days = check_window_days if check_window_days is not None else settings.repetition_window_days

    recipe_row = await recipe_db.fetch_one(
        "SELECT cuisine, ingredients FROM recipes WHERE id = ?", (recipe_id,)
    )
    if recipe_row is None:
        raise ValueError(f"No recipe found with id {recipe_id!r}.")
    candidate_cuisine = recipe_row["cuisine"]
    candidate_ingredients = [item["name"] for item in json.loads(recipe_row["ingredients"])]
    candidate_protein = derive_protein(candidate_ingredients)

    last_cooked_row = await user_db.fetch_one(
        "SELECT date FROM meal_history WHERE recipe_id = ? ORDER BY date DESC LIMIT 1", (recipe_id,)
    )
    last_cooked = date_.fromisoformat(last_cooked_row["date"]) if last_cooked_row is not None else None

    window_rows = await user_db.fetch_all(
        "SELECT recipe_id, cuisine, ingredients_used FROM meal_history WHERE date >= date('now', ?)",
        (f"-{window_days} days",),
    )

    # Level 1: exact repeat. Any window row for this exact recipe_id
    # means last_cooked (the overall most recent date for it) must
    # itself already fall inside the window.
    if any(row["recipe_id"] == recipe_id for row in window_rows):
        assert last_cooked is not None
        days_ago = (date_.today() - last_cooked).days
        return RepetitionCheck(
            repetition_score=_EXACT_REPEAT_SCORE,
            reason=(
                f"This exact recipe was already cooked {days_ago} day(s) ago, "
                f"within the {window_days}-day window."
            ),
            recommendation="too_repetitive",
            last_cooked=last_cooked,
        )

    # Level 2: protein repetition. window_rows can't contain the
    # candidate recipe itself here (level 1 already returned if it did),
    # so every row counted below is genuinely a different meal.
    if candidate_protein is not None:
        recipe_ids_needed = {row["recipe_id"] for row in window_rows if row["recipe_id"] is not None}
        ingredients_by_recipe = await load_recipe_ingredient_names(recipe_db, recipe_ids_needed)

        protein_count = 0
        for row in window_rows:
            names = await _meal_ingredient_names(
                row["recipe_id"], row["ingredients_used"], ingredients_by_recipe
            )
            if derive_protein(names) == candidate_protein:
                protein_count += 1

        if protein_count > settings.max_same_protein_per_week:
            return RepetitionCheck(
                repetition_score=_PROTEIN_REPETITION_SCORE,
                reason=(
                    f"{candidate_protein} has already appeared {protein_count} time(s) in the last "
                    f"{window_days} days, above the configured limit of "
                    f"{settings.max_same_protein_per_week}."
                ),
                recommendation="suggest_alternative",
                last_cooked=last_cooked,
            )

    # Level 3: cuisine dominance.
    if candidate_cuisine:
        cuisine_rows = [row for row in window_rows if row["cuisine"]]
        if len(cuisine_rows) >= _MIN_WINDOW_MEALS_FOR_CUISINE_CHECK:
            same_cuisine_count = sum(1 for row in cuisine_rows if row["cuisine"] == candidate_cuisine)
            share = same_cuisine_count / len(cuisine_rows)
            if share >= _CUISINE_DOMINANCE_THRESHOLD:
                return RepetitionCheck(
                    repetition_score=_CUISINE_DOMINANCE_SCORE,
                    reason=(
                        f"{candidate_cuisine} cuisine already makes up {same_cuisine_count} of "
                        f"{len(cuisine_rows)} cuisine-known meals in the last {window_days} days."
                    ),
                    recommendation="suggest_alternative",
                    last_cooked=last_cooked,
                )

    return RepetitionCheck(
        repetition_score=_NO_REPETITION_SCORE,
        reason="No repetition concerns in the checked window.",
        recommendation="acceptable",
        last_cooked=last_cooked,
    )
