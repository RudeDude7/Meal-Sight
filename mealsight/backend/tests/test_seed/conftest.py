"""Fixtures for mealsight.seed tests: a fresh recipes.db Database per
test under tmp_path — never the real data/ directory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database


@pytest.fixture
async def recipe_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "recipes_test.db", name="recipes", schema_path=SCHEMA_DIR / "recipes.sql")
    await init_database(db, db.schema_path)
    yield db
    await db.close()
