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
from mealsight.recipe_engine.models import RecipeDetail, RecipeIngredient, RecipeSummary


def _parse_dietary_tags(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


async def search_recipes(
    db: Database,
    dietary_filters: Sequence[str],
    max_cook_time: int,
    cuisine: str | None = None,
    meal_type: str | None = None,
    max_results: int = 20,
) -> list[RecipeSummary]:
    """Searches recipes by hard filters, returning compact summaries.

    dietary_filters is a hard constraint applied after the SQL query
    (dietary_tags is stored as JSON, not queryable directly in SQL): a
    recipe is excluded entirely unless it carries every one of the
    requested tags — never included but ranked lower. Recipes with no
    known cook_time_minutes are excluded from a max_cook_time filter,
    since there's no way to confirm they meet it.
    """
    query = "SELECT id, name, cuisine, meal_type, cook_time_minutes, dietary_tags FROM recipes "
    query += "WHERE cook_time_minutes IS NOT NULL AND cook_time_minutes <= ?"
    params: list[Any] = [max_cook_time]

    if cuisine is not None:
        query += " AND cuisine = ?"
        params.append(cuisine)
    if meal_type is not None:
        query += " AND meal_type = ?"
        params.append(meal_type)
    query += " ORDER BY name"

    rows = await db.fetch_all(query, params)

    required_tags = set(dietary_filters)
    results: list[RecipeSummary] = []
    for row in rows:
        tags = _parse_dietary_tags(row["dietary_tags"])
        if not required_tags.issubset(tags):
            continue
        results.append(
            RecipeSummary(
                id=row["id"],
                name=row["name"],
                cuisine=row["cuisine"],
                meal_type=row["meal_type"],
                cook_time_minutes=row["cook_time_minutes"],
                dietary_tags=tags,
            )
        )
        if len(results) >= max_results:
            break

    return results


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
