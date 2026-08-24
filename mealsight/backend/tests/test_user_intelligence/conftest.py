"""Fixtures for mealsight.user_intelligence tests: a fresh
user_intelligence.db Database per test under tmp_path — never the real
data/ directory. Every mealsight.user_intelligence function takes its
Database (and, for the ingredient-canonicalizing ones, its synonym_map)
as an explicit optional argument specifically so tests like these can
pass a hand-built one directly, without needing a second real database
or touching any process-wide singleton.
"""

from __future__ import annotations

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
