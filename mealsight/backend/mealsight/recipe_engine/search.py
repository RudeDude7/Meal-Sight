"""search_recipes and get_recipe — querying the local recipes table.

Deterministic, no LLM calls. Dietary filters are hard constraints: a
recipe missing a required tag is excluded outright, never ranked lower —
there is no partial credit for "almost vegan."
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mealsight.db.connection import Database
from mealsight.recipe_engine.models import RecipeDetail, RecipeIngredient, RecipeSummary, SearchResults


def _parse_dietary_tags(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


async def search_recipes(
    db: Database,
    dietary_filters: Sequence[str],
    max_cook_time: int | None = None,
    cuisine: str | None = None,
    meal_type: str | None = None,
    max_results: int = 20,
) -> SearchResults:
    """Searches recipes by hard filters, returning compact summaries.

    dietary_filters is a hard constraint applied after the SQL query
    (dietary_tags is stored as JSON, not queryable directly in SQL): a
    recipe is excluded entirely unless it carries every one of the
    requested tags — never included but ranked lower. When max_cook_time
    is given, recipes with no known cook_time_minutes are excluded from
    it, since there's no way to confirm they meet it; when max_cook_time
    is None, cook time isn't filtered on at all, known or unknown.

    The returned SearchResults carries both the (possibly capped)
    results list and total_matched — the count of every recipe that
    satisfied every filter, before max_results cut the list down. A
    caller needs both to tell "only 3 recipes matched" apart from
    "200 matched, here are the first 3".
    """
    query = "SELECT id, name, cuisine, meal_type, cook_time_minutes, dietary_tags FROM recipes WHERE 1=1"
    params: list[Any] = []

    if max_cook_time is not None:
        query += " AND cook_time_minutes IS NOT NULL AND cook_time_minutes <= ?"
        params.append(max_cook_time)
    if cuisine is not None:
        query += " AND cuisine = ?"
        params.append(cuisine)
    if meal_type is not None:
        query += " AND meal_type = ?"
        params.append(meal_type)
    query += " ORDER BY name"

    rows = await db.fetch_all(query, params)

    required_tags = set(dietary_filters)
    matched: list[RecipeSummary] = []
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
