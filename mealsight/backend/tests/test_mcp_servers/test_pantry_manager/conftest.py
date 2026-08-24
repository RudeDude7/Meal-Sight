"""Fixtures for the pantry-manager MCP server tests.

server.py's tools each call mealsight.db.get_pantry_db() directly (the
same process-wide singleton pattern the rest of this codebase uses)
rather than taking a Database as an argument — so making these tests
isolated means repointing that singleton at a fresh, throwaway database
per test, not just constructing one and passing it in. Several tools
(update_pantry, remove_items, create_grocery_list) also resolve
canonical ingredient names via mealsight.matching.synonyms, which reads
ingredient_synonyms out of recipes.db — not pantry.db — so a fresh
recipe db needs to exist too, even when a test never touches recipes
directly, or load_synonym_map has nothing to query.

_fresh_pantry_db does all of that: monkeypatches both settings.pantry_db_path
and settings.recipes_db_path to tmp_path files, resets every process-wide
cache this stack has (both Database singletons, plus mealsight.matching's
synonym cache and mealsight.pantry's shelf-life cache), and applies both
real schemas, before every single test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from mealsight.config.settings import settings
from mealsight.db import close_all, get_pantry_db, get_recipe_db
from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.matching.synonyms import reset_synonym_cache
from mealsight.mcp_servers.pantry_manager.server import mcp
from mealsight.pantry.shelf_life import reset_shelf_life_cache


@pytest.fixture(autouse=True)
async def _fresh_pantry_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(settings, "pantry_db_path", tmp_path / "pantry_test.db")
    monkeypatch.setattr(settings, "recipes_db_path", tmp_path / "recipes_test.db")
    await close_all()
    reset_synonym_cache()
    reset_shelf_life_cache()

    pantry_db = get_pantry_db()
    await init_database(pantry_db, SCHEMA_DIR / "pantry.sql")
    recipe_db = get_recipe_db()
    await init_database(recipe_db, SCHEMA_DIR / "recipes.sql")

    yield

    await close_all()
    reset_synonym_cache()
    reset_shelf_life_cache()


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client[Any]]:
    async with Client(mcp) as client:
        yield client


async def insert_pantry_item(
    *,
    name: str,
    quantity: float | None = 1.0,
    unit: str | None = "count",
    category: str = "vegetable",
    freshness_status: str = "fresh",
    estimated_shelf_days: int | None = 7,
    added_days_ago: int = 0,
) -> None:
    db = get_pantry_db()
    await db.execute(
        f"""
        INSERT INTO pantry (
            name, quantity, unit, category, freshness_status, estimated_shelf_days,
            added_date, last_seen_date, source
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now', '-{added_days_ago} days'),
                  datetime('now', '-{added_days_ago} days'), 'photo')
        """,
        (name, quantity, unit, category, freshness_status, estimated_shelf_days),
    )


async def insert_shelf_life(
    item_name: str,
    category: str,
    *,
    shelf_days_refrigerated: int | None = None,
    shelf_days_frozen: int | None = None,
    shelf_days_pantry: int | None = None,
) -> None:
    db: Database = get_pantry_db()
    await db.execute(
        """
        INSERT INTO shelf_life_reference (
            item_name, category, shelf_days_refrigerated, shelf_days_frozen, shelf_days_pantry
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (item_name, category, shelf_days_refrigerated, shelf_days_frozen, shelf_days_pantry),
    )
