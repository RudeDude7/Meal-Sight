"""Fixtures for the user-intelligence MCP server tests.

server.py's tools each call mealsight.db.get_user_db() directly (the
same process-wide singleton pattern the other two MCP servers use)
rather than taking a Database as an argument — so making these tests
isolated means repointing that singleton at a fresh, throwaway database
per test. log_meal/check_repetition also read recipes.db (for cook_time_
minutes, cuisine, and ingredients), and disliked_ingredients-style
canonicalization isn't used here at all, but the recipe read is real, so
a fresh recipes.db needs to exist too.

_fresh_user_db does all of that: monkeypatches both settings.
user_intelligence_db_path and settings.recipes_db_path to tmp_path
files, resets the process-wide Database singletons, and applies both
real schemas, before every single test.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from mealsight.config.settings import settings
from mealsight.db import close_all, get_recipe_db, get_user_db
from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.mcp_servers.user_intelligence.server import mcp


@pytest.fixture(autouse=True)
async def _fresh_user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(settings, "user_intelligence_db_path", tmp_path / "user_intelligence_test.db")
    monkeypatch.setattr(settings, "recipes_db_path", tmp_path / "recipes_test.db")
    await close_all()

    user_db = get_user_db()
    await init_database(user_db, SCHEMA_DIR / "user_intelligence.sql")
    recipe_db = get_recipe_db()
    await init_database(recipe_db, SCHEMA_DIR / "recipes.sql")

    yield

    await close_all()


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client[Any]]:
    async with Client(mcp) as client:
        yield client


async def insert_recipe(
    *,
    recipe_id: str,
    name: str,
    cuisine: str | None = None,
    cook_time_minutes: int | None = None,
    ingredients: list[str] | None = None,
) -> None:
    db: Database = get_recipe_db()
    ingredient_objects = [
        {"name": n, "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        for n in (ingredients or [])
    ]
    await db.execute(
        "INSERT INTO recipes (id, name, cuisine, cook_time_minutes, ingredients, steps) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            recipe_id,
            name,
            cuisine,
            cook_time_minutes,
            json.dumps(ingredient_objects),
            json.dumps(["Cook it."]),
        ),
    )
