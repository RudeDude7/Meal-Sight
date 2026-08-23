"""Shared fixtures for db layer tests. Every Database here points at a
file under pytest's tmp_path, never at the real data/ directory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mealsight.db.connection import SCHEMA_DIR, Database


@pytest.fixture
async def pantry_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "pantry_test.db", name="pantry", schema_path=SCHEMA_DIR / "pantry.sql")
    yield db
    await db.close()


@pytest.fixture
async def recipe_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "recipes_test.db", name="recipes", schema_path=SCHEMA_DIR / "recipes.sql")
    yield db
    await db.close()


@pytest.fixture
async def user_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(
        tmp_path / "user_test.db",
        name="user_intelligence",
        schema_path=SCHEMA_DIR / "user_intelligence.sql",
    )
    yield db
    await db.close()
