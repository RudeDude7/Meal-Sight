"""Confirms a completely fresh database directory — no .db files at
all, exactly what a brand-new Docker volume, a freshly cloned repo, or
an HF Spaces rebuild starts with — produces working servers through
nothing but each server's own __main__ startup sequence. No manual
`init_all_databases()` call, no test-only schema-setup fixture: this
test deliberately calls the SAME functions each server's own `main()`
calls, not a shortcut around them, since the whole point is proving the
real startup path works unattended.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from mealsight.config.settings import settings
from mealsight.db import close_all, get_pantry_db, get_recipe_db, get_user_db
from mealsight.matching.substitutions import reset_substitution_cache
from mealsight.matching.synonyms import reset_synonym_cache

pantry_main = importlib.import_module("mealsight.mcp_servers.pantry_manager.__main__")
recipe_main = importlib.import_module("mealsight.mcp_servers.recipe_engine.__main__")
user_main = importlib.import_module("mealsight.mcp_servers.user_intelligence.__main__")

from mealsight.mcp_servers.pantry_manager.server import mcp as pantry_mcp  # noqa: E402
from mealsight.mcp_servers.recipe_engine.server import mcp as recipe_mcp  # noqa: E402
from mealsight.mcp_servers.user_intelligence.server import mcp as user_mcp  # noqa: E402


@pytest.fixture(autouse=True)
async def _fresh_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    # tmp_path itself is guaranteed empty by pytest — none of these three
    # paths exist on disk yet, the exact condition a fresh deployment
    # starts from.
    monkeypatch.setattr(settings, "pantry_db_path", tmp_path / "pantry.db")
    monkeypatch.setattr(settings, "recipes_db_path", tmp_path / "recipes.db")
    monkeypatch.setattr(settings, "user_intelligence_db_path", tmp_path / "user_intelligence.db")
    await close_all()
    reset_synonym_cache()
    reset_substitution_cache()

    yield

    await close_all()


async def test_user_intelligence_server_works_from_a_fresh_directory_with_no_manual_step() -> None:
    assert not settings.user_intelligence_db_path.exists()

    await user_main._initialize_schema()
    await user_main._verify_database_reachable()

    async with Client(user_mcp) as client:
        result = await client.call_tool("get_user_profile", {})

    assert result.data["dietary_restrictions"] == []
    assert result.data["cuisine_preferences"] == {}


async def test_recipe_engine_server_works_from_a_fresh_directory_with_no_manual_step() -> None:
    assert not settings.recipes_db_path.exists()

    await recipe_main._initialize_schema()
    # This logs a loud warning (0 rows) rather than raising — an empty,
    # unseeded recipes table is a real, expected state right after a
    # fresh deploy, before `mealsight-seed` has ever run; the point of
    # this test is that the SCHEMA works unattended, not that recipe
    # DATA magically appears without ever running the seed step.
    await recipe_main._verify_recipes_seeded()

    async with Client(recipe_mcp) as client:
        result = await client.call_tool("search_recipes", {"max_results": 5})

    assert result.data == {"results": [], "total_matched": 0}


async def test_pantry_manager_server_works_from_a_fresh_directory_with_no_manual_step() -> None:
    assert not settings.pantry_db_path.exists()

    await pantry_main._initialize_schema()
    await pantry_main._seed_shelf_life_reference()

    async with Client(pantry_mcp) as client:
        result = await client.call_tool("get_pantry", {})

    assert result.data == {"items": [], "count": 0}

    # shelf_life_reference is local, no-network seed data — unlike
    # recipes, this one really is expected to be populated automatically
    # on every boot, fresh directory or not.
    db = get_pantry_db()
    row = await db.fetch_one("SELECT COUNT(*) as count FROM shelf_life_reference")
    assert row is not None
    assert row["count"] > 0


async def test_all_three_databases_did_not_exist_before_this_test_and_do_after() -> None:
    """A slightly different angle on the same guarantee: run every
    server's own startup sequence, then confirm the .db files
    themselves now exist on disk with their own real schema — not just
    that a query happened to succeed against an in-memory state."""
    await user_main._initialize_schema()
    await recipe_main._initialize_schema()
    await pantry_main._initialize_schema()

    assert settings.user_intelligence_db_path.exists()
    assert settings.recipes_db_path.exists()
    assert settings.pantry_db_path.exists()

    user_tables = await _table_names(get_user_db())
    recipe_tables = await _table_names(get_recipe_db())
    pantry_tables = await _table_names(get_pantry_db())

    assert "meal_history" in user_tables
    assert "interaction_history" in user_tables
    assert "recipes" in recipe_tables
    assert "pantry" in pantry_tables
    assert "shelf_life_reference" in pantry_tables


async def _table_names(db: Any) -> list[str]:
    rows = await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return [row["name"] for row in rows]
