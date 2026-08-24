"""Fixtures for the recipe-engine MCP server tests.

server.py's tools each call mealsight.db.get_recipe_db() directly (the
same process-wide singleton pattern the rest of this codebase uses)
rather than taking a Database as an argument — so making these tests
isolated means repointing that singleton at a fresh, throwaway database
per test, not just constructing one and passing it in. _fresh_recipe_db
does exactly that: monkeypatches settings.recipes_db_path to a tmp_path
file, resets every process-wide cache this stack has (the Database
singleton itself, plus mealsight.matching's synonym/substitution
caches), and applies the real schema, before every single test.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from mealsight.config.settings import settings
from mealsight.db import close_all, get_recipe_db
from mealsight.db.connection import SCHEMA_DIR
from mealsight.db.init import init_database
from mealsight.matching.substitutions import reset_substitution_cache
from mealsight.matching.synonyms import reset_synonym_cache
from mealsight.mcp_servers.recipe_engine.server import mcp


@pytest.fixture(autouse=True)
async def _fresh_recipe_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(settings, "recipes_db_path", tmp_path / "recipes_test.db")
    await close_all()
    reset_synonym_cache()
    reset_substitution_cache()

    db = get_recipe_db()
    await init_database(db, SCHEMA_DIR / "recipes.sql")

    yield

    await close_all()
    reset_synonym_cache()
    reset_substitution_cache()


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client[Any]]:
    async with Client(mcp) as client:
        yield client


async def insert_recipe(
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
    db = get_recipe_db()
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
    ingredient: str,
    *,
    calories: float,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float = 0.0,
    sodium: float = 0.0,
) -> None:
    db = get_recipe_db()
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
    original_ingredient: str,
    substitute: str,
    *,
    ratio: str = "1:1",
    flavor_impact: str = "noticeable",
    notes: str | None = None,
) -> None:
    db = get_recipe_db()
    await db.execute(
        """
        INSERT INTO substitutions (original_ingredient, substitute, ratio, flavor_impact, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (original_ingredient, substitute, ratio, flavor_impact, notes),
    )
