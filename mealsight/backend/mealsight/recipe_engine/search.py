"""search_recipes and get_recipe — querying the local recipes table.

Deterministic, no LLM calls. Dietary filters are hard constraints: a
recipe missing a required tag is excluded outright, never ranked lower —
there is no partial credit for "almost vegan."

ORDERING, since phase 6.4's own finding: with no pantry context, results
still sort alphabetically by name (a plain browsing search — "show me
Italian dinners" — has no ingredient list to rank against, so name order
is the only stable, meaningful order available). But when a caller
DOES supply pantry_ingredients (the agent's own search node always
does), results are pre-ranked by a cheap pantry-overlap heuristic before
max_results ever caps the list — see _pantry_overlap_score below. This
is deliberately NOT the same thing as match_ingredients' own full
scoring (importance weighting, substitutions, partial-specificity
matches): it exists purely to make sure a cookable recipe with a
late-alphabet name is actually IN the top max_results candidates for
match_ingredients to find, not lost to alphabetical order before it's
ever considered.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.recipe_engine.models import RecipeDetail, RecipeIngredient, RecipeSummary, SearchResults


def _parse_dietary_tags(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


def _pantry_overlap_score(ingredients_json: str, pantry_canonical: set[str], synonym_map: Any) -> float:
    """Fraction (0.0-1.0) of this recipe's own ingredients whose
    canonical name is in the pantry — the SAME normalize_ingredient +
    resolve_canonical pipeline mealsight.matching's own real matcher
    uses, so this pre-ranking agrees with what match_ingredients would
    actually find rather than using a cheaper, looser comparison that
    could rank a recipe match_ingredients would score very differently.
    An ingredient-free (never happens in practice — NOT NULL, non-empty
    JSON) or zero-ingredient recipe scores 0.0, not a division error."""
    items = json.loads(ingredients_json)
    if not items:
        return 0.0
    matched = 0
    for item in items:
        name = item.get("name")
        if not name:
            continue
        canonical = resolve_canonical(normalize_ingredient(name), synonym_map)
        if canonical in pantry_canonical:
            matched += 1
    return matched / len(items)


async def search_recipes(
    db: Database,
    dietary_filters: Sequence[str],
    max_cook_time: int | None = None,
    cuisine: str | None = None,
    meal_type: str | Sequence[str] | None = None,
    max_results: int = 20,
    pantry_ingredients: Sequence[str] | None = None,
) -> SearchResults:
    """Searches recipes by hard filters, returning compact summaries.

    dietary_filters is a hard constraint applied after the SQL query
    (dietary_tags is stored as JSON, not queryable directly in SQL): a
    recipe is excluded entirely unless it carries every one of the
    requested tags — never included but ranked lower. When max_cook_time
    is given, recipes with no known cook_time_minutes are excluded from
    it, since there's no way to confirm they meet it; when max_cook_time
    is None, cook time isn't filtered on at all, known or unknown.

    meal_type accepts EITHER a single exact value (a direct, human-driven
    search — "show me desserts") OR a sequence of acceptable values (the
    agent's own time-of-day inference, which maps onto several real
    corpus categories at once — see agent/nodes/search_recipes.py's own
    MEAL_TYPE_TO_CORPUS_TYPES for why a single inferred "dinner" has to
    mean "main OR side" against this specific corpus's own vocabulary).

    pantry_ingredients, when given, pre-ranks results by pantry-overlap
    (see _pantry_overlap_score) before max_results caps the list — see
    this module's own docstring. Omit it for a plain browsing search
    with no pantry context, which keeps the existing alphabetical order.

    The returned SearchResults carries both the (possibly capped)
    results list and total_matched — the count of every recipe that
    satisfied every filter, before max_results cut the list down. A
    caller needs both to tell "only 3 recipes matched" apart from
    "200 matched, here are the first 3".
    """
    query = (
        "SELECT id, name, cuisine, meal_type, cook_time_minutes, dietary_tags, ingredients "
        "FROM recipes WHERE 1=1"
    )
    params: list[Any] = []

    if max_cook_time is not None:
        query += " AND cook_time_minutes IS NOT NULL AND cook_time_minutes <= ?"
        params.append(max_cook_time)
    if cuisine is not None:
        query += " AND cuisine = ?"
        params.append(cuisine)
    if meal_type is not None:
        if isinstance(meal_type, str):
            query += " AND meal_type = ?"
            params.append(meal_type)
        else:
            meal_types = list(meal_type)
            if meal_types:
                placeholders = ",".join("?" for _ in meal_types)
                query += f" AND meal_type IN ({placeholders})"
                params.extend(meal_types)
    query += " ORDER BY name"

    rows = await db.fetch_all(query, params)

    pantry_canonical: set[str] | None = None
    synonym_map: dict[str, str] = {}
    if pantry_ingredients:
        synonym_map = await load_synonym_map(db)
        pantry_canonical = {
            resolve_canonical(normalize_ingredient(name), synonym_map) for name in pantry_ingredients
        }

    required_tags = set(dietary_filters)
    matched: list[RecipeSummary] = []
    overlap_scores: dict[str, float] = {}
    for row in rows:
        tags = _parse_dietary_tags(row["dietary_tags"])
        if not required_tags.issubset(tags):
            continue
        matched.append(
            RecipeSummary(
                id=row["id"],
                name=row["name"],
                cuisine=row["cuisine"],
                meal_type=row["meal_type"],
                cook_time_minutes=row["cook_time_minutes"],
                dietary_tags=tags,
            )
        )
        if pantry_canonical is not None:
            overlap_scores[row["id"]] = _pantry_overlap_score(
                row["ingredients"], pantry_canonical, synonym_map
            )

    if pantry_canonical is not None:
        # Stable sort: recipes tied on overlap (most commonly 0.0, no
        # overlap at all) keep the SQL query's own alphabetical order
        # as a deterministic tiebreak, rather than an arbitrary one.
        matched.sort(key=lambda r: overlap_scores.get(r.id, 0.0), reverse=True)

    return SearchResults(results=matched[:max_results], total_matched=len(matched))


async def get_recipe(db: Database, recipe_id: str) -> RecipeDetail:
    """Fetches one recipe in full, with ingredients parsed out of their
    JSON column. Raises ValueError if no recipe with that id exists."""
    row = await db.fetch_one(
        "SELECT id, name, cuisine, meal_type, cook_time_minutes, difficulty, servings_base, "
        "dietary_tags, ingredients, steps, image_url FROM recipes WHERE id = ?",
        (recipe_id,),
    )
    if row is None:
        raise ValueError(f"No recipe found with id {recipe_id!r}")

    raw_ingredients: list[dict[str, Any]] = json.loads(row["ingredients"])
    ingredients = [
        RecipeIngredient(
            name=item["name"],
            quantity=item["quantity"],
            unit=item["unit"],
            importance=item["importance"],
            raw_measure=item.get("raw_measure"),
        )
        for item in raw_ingredients
    ]

    return RecipeDetail(
        id=row["id"],
        name=row["name"],
        cuisine=row["cuisine"],
        meal_type=row["meal_type"],
        cook_time_minutes=row["cook_time_minutes"],
        difficulty=row["difficulty"],
        servings_base=row["servings_base"],
        dietary_tags=_parse_dietary_tags(row["dietary_tags"]),
        ingredients=ingredients,
        steps=json.loads(row["steps"]),
        image_url=row["image_url"],
    )
