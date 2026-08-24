"""Fixtures for mealsight.user_intelligence tests: a fresh
user_intelligence.db Database per test under tmp_path — never the real
data/ directory. Every mealsight.user_intelligence function takes its
Database (and, for the ingredient-canonicalizing ones, its synonym_map)
as an explicit optional argument specifically so tests like these can
pass a hand-built one directly, without needing a second real database
or touching any process-wide singleton.

scoring.recompute_preference_scores and repetition.check_repetition both
need a real recipes.db too (for a rated/checked meal's cuisine and
ingredients) — recipe_db is a second, equally fresh, equally throwaway
Database for that, and insert_recipe is the one helper both test modules
that need it actually use to populate it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database


@pytest.fixture
async def user_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(
        tmp_path / "user_intelligence_test.db",
        name="user_intelligence",
        schema_path=SCHEMA_DIR / "user_intelligence.sql",
    )
    await init_database(db, db.schema_path)
    yield db
    await db.close()


@pytest.fixture
async def recipe_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(
        tmp_path / "recipes_test.db",
        name="recipes",
        schema_path=SCHEMA_DIR / "recipes.sql",
    )
    await init_database(db, db.schema_path)
    yield db
    await db.close()


async def insert_recipe(
    recipe_db: Database,
    *,
    recipe_id: str,
    name: str,
    cuisine: str | None = None,
    ingredients: list[str] | None = None,
) -> None:
    ingredient_objects = [
        {"name": name, "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        for name in (ingredients or [])
    ]
    await recipe_db.execute(
        "INSERT INTO recipes (id, name, cuisine, ingredients, steps) VALUES (?, ?, ?, ?, ?)",
        (recipe_id, name, cuisine, json.dumps(ingredient_objects), json.dumps(["Cook it."])),
    )
