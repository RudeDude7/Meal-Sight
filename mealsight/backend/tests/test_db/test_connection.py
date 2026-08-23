"""Tests for mealsight.db.connection.Database."""

from __future__ import annotations

import asyncio

from mealsight.db.connection import Database
from mealsight.db.init import init_database


async def test_foreign_keys_and_wal_pragmas_are_set_on_a_live_connection(pantry_db: Database) -> None:
    connection = await pantry_db._ensure_connection()

    foreign_keys_rows = list(await connection.execute_fetchall("PRAGMA foreign_keys"))
    journal_mode_rows = list(await connection.execute_fetchall("PRAGMA journal_mode"))

    assert foreign_keys_rows[0][0] == 1
    assert str(journal_mode_rows[0][0]).lower() == "wal"


async def test_transaction_commits_on_success(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)

    async with pantry_db.transaction() as connection:
        await connection.execute(
            "INSERT INTO pantry (name, category) VALUES (?, ?)", ("banana", "fruit")
        )

    row = await pantry_db.fetch_one("SELECT name FROM pantry WHERE name = ?", ("banana",))
    assert row is not None
    assert row["name"] == "banana"


async def test_transaction_rolls_back_on_exception(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)

    class _BoomError(Exception):
        pass

    try:
        async with pantry_db.transaction() as connection:
            await connection.execute(
                "INSERT INTO pantry (name, category) VALUES (?, ?)", ("banana", "fruit")
            )
            raise _BoomError("something went wrong after the insert")
    except _BoomError:
        pass

    row = await pantry_db.fetch_one("SELECT name FROM pantry WHERE name = ?", ("banana",))
    assert row is None


async def test_fetch_one_returns_none_when_no_row_matches(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)

    row = await pantry_db.fetch_one("SELECT * FROM pantry WHERE name = ?", ("does-not-exist",))

    assert row is None


async def test_rows_support_mapping_access_by_column_name(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)
    await pantry_db.execute(
        "INSERT INTO pantry (name, category, quantity, unit) VALUES (?, ?, ?, ?)",
        ("onion", "vegetable", 3.0, "count"),
    )

    row = await pantry_db.fetch_one(
        "SELECT name, category, quantity, unit FROM pantry WHERE name = ?", ("onion",)
    )

    assert row is not None
    assert row["name"] == "onion"
    assert row["category"] == "vegetable"
    assert row["quantity"] == 3.0
    assert row["unit"] == "count"


async def test_concurrent_writes_do_not_raise_database_is_locked(pantry_db: Database) -> None:
    await init_database(pantry_db, pantry_db.schema_path)

    async def insert_one(index: int) -> None:
        await pantry_db.execute(
            "INSERT INTO pantry (name, category) VALUES (?, ?)", (f"item-{index}", "other")
        )

    await asyncio.gather(*(insert_one(i) for i in range(25)))

    row = await pantry_db.fetch_one("SELECT COUNT(*) as count FROM pantry")
    assert row is not None
    assert row["count"] == 25
