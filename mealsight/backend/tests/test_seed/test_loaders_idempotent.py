"""Confirms every loader is idempotent: running it twice against the same
database yields identical row counts, never duplicates."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.seed.load_nutrition import load_nutrition
from mealsight.seed.load_substitutions import load_substitutions
from mealsight.seed.load_synonyms import load_synonyms
from mealsight.seed.recipes_from_mealdb import build_recipe_row, ensure_cook_time_source_column, upsert_recipe

_FIXTURE_MEAL = {
    "idMeal": "99999",
    "strMeal": "Test Chicken Curry",
    "strCategory": "Chicken",
    "strArea": "Indian",
    "strCountry": None,
    "strInstructions": "Fry the onion and garlic for 5 minutes. Simmer for 20 minutes.",
    "strMealThumb": "https://example.test/thumb.jpg",
    "strSource": "https://example.test/recipe",
    "strIngredient1": "Chicken", "strMeasure1": "500g",
    "strIngredient2": "Onion", "strMeasure2": "1",
    "strIngredient3": "Salt", "strMeasure3": "Pinch",
    **{f"strIngredient{i}": "" for i in range(4, 21)},
    **{f"strMeasure{i}": "" for i in range(4, 21)},
}


async def _row_count(db: Database, table: str) -> int:
    row = await db.fetch_one(f"SELECT COUNT(*) as count FROM {table}")
    assert row is not None
    return int(row["count"])


async def test_load_substitutions_is_idempotent(recipe_db: Database) -> None:
    await load_substitutions(recipe_db)
    first_count = await _row_count(recipe_db, "substitutions")

    await load_substitutions(recipe_db)
    second_count = await _row_count(recipe_db, "substitutions")

    assert first_count == second_count
    assert first_count > 0


async def test_load_synonyms_is_idempotent(recipe_db: Database) -> None:
    await load_synonyms(recipe_db)
    first_count = await _row_count(recipe_db, "ingredient_synonyms")

    await load_synonyms(recipe_db)
    second_count = await _row_count(recipe_db, "ingredient_synonyms")

    assert first_count == second_count
    assert first_count > 0


async def test_load_nutrition_is_idempotent(recipe_db: Database) -> None:
    await load_nutrition(recipe_db)
    first_count = await _row_count(recipe_db, "nutrition_reference")

    await load_nutrition(recipe_db)
    second_count = await _row_count(recipe_db, "nutrition_reference")

    assert first_count == second_count
    assert first_count > 0


async def test_recipe_upsert_is_idempotent(recipe_db: Database) -> None:
    # Uses a hand-written fixture meal record, not a live TheMealDB call.
    await ensure_cook_time_source_column(recipe_db)
    row = build_recipe_row(_FIXTURE_MEAL)

    await upsert_recipe(recipe_db, row)
    first_count = await _row_count(recipe_db, "recipes")

    await upsert_recipe(recipe_db, row)
    second_count = await _row_count(recipe_db, "recipes")

    assert first_count == second_count == 1
