"""Fixtures and helpers for mealsight.recipe_engine tests: a fresh
recipes.db Database per test under tmp_path — never the real data/
directory — plus small helpers for inserting hand-built test rows."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.matching.substitutions import reset_substitution_cache
from mealsight.matching.synonyms import reset_synonym_cache


@pytest.fixture(autouse=True)
def _reset_matching_caches() -> None:
    # mealsight.matching.synonyms/substitutions cache their DB-loaded maps
    # process-wide, keyed by nothing — a call against one Database
    # instance would otherwise leak into every later call against a
    # different one. Each test here gets its own fresh, empty
    # recipe_db, so without this reset, whichever test happens to run
    # first would silently decide what every later test sees.
    reset_synonym_cache()
    reset_substitution_cache()


@pytest.fixture
async def recipe_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "recipes_test.db", name="recipes", schema_path=SCHEMA_DIR / "recipes.sql")
    await init_database(db, db.schema_path)
    yield db
    await db.close()


async def insert_recipe(
    db: Database,
    *,
    recipe_id: str,
    name: str,
    ingredients: list[dict[str, Any]],
    steps: list[str] | None = None,
    cuisine: str | None = None,
    meal_type: str | None = None,
    cook_time_minutes: int | None = None,
    servings_base: int = 4,
    dietary_tags: list[str] | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO recipes (
            id, name, cuisine, meal_type, cook_time_minutes, servings_base,
            dietary_tags, ingredients, steps
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recipe_id,
            name,
            cuisine,
            meal_type,
            cook_time_minutes,
            servings_base,
            json.dumps(dietary_tags or []),
            json.dumps(ingredients),
            json.dumps(steps or ["Cook it."]),
        ),
    )


async def insert_nutrition(
    db: Database,
    ingredient: str,
    *,
    calories: float,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float = 0.0,
    sodium: float = 0.0,
) -> None:
    await db.execute(
        """
        INSERT INTO nutrition_reference (
            ingredient, calories_per_100g, protein_per_100g, carbs_per_100g,
            fat_per_100g, fiber_per_100g, sodium_per_100g
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ingredient, calories, protein, carbs, fat, fiber, sodium),
    )


async def insert_substitution(
    db: Database,
    original_ingredient: str,
    substitute: str,
    *,
    ratio: str = "1:1",
    flavor_impact: str = "noticeable",
    notes: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO substitutions (original_ingredient, substitute, ratio, flavor_impact, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (original_ingredient, substitute, ratio, flavor_impact, notes),
    )
