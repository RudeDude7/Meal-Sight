"""Tests for mealsight.db.init."""

from __future__ import annotations

import pytest

from mealsight.db.connection import Database
from mealsight.db.init import init_database, reset_database


async def _table_names(db: Database) -> list[str]:
    rows = await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return [row["name"] for row in rows]


async def test_init_is_idempotent(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)
    first_tables = await _table_names(pantry_db)

    await init_database(pantry_db, pantry_db.schema_path)
    second_tables = await _table_names(pantry_db)

    assert first_tables == second_tables
    assert "pantry" in first_tables


async def test_init_idempotent_preserves_existing_rows(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)
    await pantry_db.execute("INSERT INTO pantry (name, category) VALUES (?, ?)", ("garlic", "vegetable"))

    await init_database(pantry_db, pantry_db.schema_path)

    row = await pantry_db.fetch_one("SELECT name FROM pantry WHERE name = ?", ("garlic",))
    assert row is not None


async def test_reset_database_refuses_without_confirm(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)

    with pytest.raises(ValueError, match="confirm=True"):
        await reset_database(pantry_db)


async def test_reset_database_drops_and_reapplies_schema(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)
    await pantry_db.execute("INSERT INTO pantry (name, category) VALUES (?, ?)", ("garlic", "vegetable"))

    await reset_database(pantry_db, confirm=True)

    tables = await _table_names(pantry_db)
    assert "pantry" in tables
    row = await pantry_db.fetch_one("SELECT name FROM pantry WHERE name = ?", ("garlic",))
    assert row is None
