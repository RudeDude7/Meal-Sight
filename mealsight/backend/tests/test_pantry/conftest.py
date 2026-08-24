"""Fixtures for mealsight.pantry tests: a fresh pantry.db Database per
test under tmp_path — never the real data/ directory. Every
mealsight.pantry function takes its Database (and, where relevant, its
synonym_map) as an explicit optional argument specifically so tests like
these can pass a hand-built one directly, without needing a second real
database or touching any process-wide singleton."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.pantry.shelf_life import reset_shelf_life_cache


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    reset_shelf_life_cache()


@pytest.fixture
async def pantry_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "pantry_test.db", name="pantry", schema_path=SCHEMA_DIR / "pantry.sql")
    await init_database(db, db.schema_path)
    yield db
    await db.close()
