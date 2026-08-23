"""Async SQLite connection layer: one Database per physical .sql file,
lazily connected, WAL-journaled, foreign-keys-on, with parameterized
query helpers and a transaction context manager.

Three physically separate databases — pantry, recipes, user_intelligence
— one per MCP server, so each server owns its data and can be developed
and tested independently. There is no cross-database join anywhere in
this layer; joining data that lives in different databases is the
agent's job, not SQL's.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from mealsight.config.settings import settings
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.db.connection")

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"

# Anything slower than this gets logged at warning, by query text and
# duration only — never by parameter values, which may hold user data.
SLOW_QUERY_THRESHOLD_MS = 100.0


class Database:
    """Wraps one SQLite database file behind a single, lazily-created
    aiosqlite connection.

    The connection is only opened on first use (lazy connection), guarded
    by a per-instance asyncio.Lock so two concurrent callers racing to
    connect at the same time don't each open a separate connection to the
    same file. Once open, every subsequent call reuses that same
    connection — aiosqlite serializes operations against one connection
    internally, which combined with WAL journaling is what keeps
    concurrent writers from raising "database is locked".
    """

    def __init__(self, path: Path, name: str, schema_path: Path) -> None:
        self.path = path
        self.name = name
        self.schema_path = schema_path
        self._connection: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()

    async def _ensure_connection(self) -> aiosqlite.Connection:
        if self._connection is not None:
            return self._connection
        async with self._connect_lock:
            if self._connection is not None:
                return self._connection
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = await aiosqlite.connect(self.path)
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA journal_mode = WAL")
            self._connection = connection
            return connection

    def _log_if_slow(self, query: str, started_at: float) -> None:
        duration_ms = (time.monotonic() - started_at) * 1000
        if duration_ms > SLOW_QUERY_THRESHOLD_MS:
            logger.warning("slow_query", db=self.name, query=query, duration_ms=round(duration_ms, 2))

    async def execute(self, query: str, params: Sequence[Any] = ()) -> int:
        """Runs one parameterized statement and commits immediately.
        Returns the connection's lastrowid — meaningful after an INSERT,
        0 otherwise."""
        connection = await self._ensure_connection()
        started_at = time.monotonic()
        cursor = await connection.execute(query, params)
        await connection.commit()
        self._log_if_slow(query, started_at)
        return cursor.lastrowid or 0

    async def execute_many(self, query: str, params_seq: Sequence[Sequence[Any]]) -> None:
        connection = await self._ensure_connection()
        started_at = time.monotonic()
        await connection.executemany(query, params_seq)
        await connection.commit()
        self._log_if_slow(query, started_at)

    async def fetch_one(self, query: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        connection = await self._ensure_connection()
        started_at = time.monotonic()
        cursor = await connection.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        self._log_if_slow(query, started_at)
        return row

    async def fetch_all(self, query: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        connection = await self._ensure_connection()
        started_at = time.monotonic()
        cursor = await connection.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        self._log_if_slow(query, started_at)
        return list(rows)

    async def executescript(self, sql: str) -> None:
        """Applies a full schema file — CREATE TABLE / CREATE INDEX
        statements. Not one of the parameterized query helpers above,
        since a schema file has no parameters to bind; used by
        mealsight.db.init, not meant for arbitrary application queries.
        """
        connection = await self._ensure_connection()
        await connection.executescript(sql)
        await connection.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Commits on successful exit, rolls back if the block raises."""
        connection = await self._ensure_connection()
        try:
            yield connection
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None


_pantry_db: Database | None = None
_recipe_db: Database | None = None
_user_db: Database | None = None


def get_pantry_db() -> Database:
    global _pantry_db
    if _pantry_db is None:
        _pantry_db = Database(settings.pantry_db_path, name="pantry", schema_path=SCHEMA_DIR / "pantry.sql")
    return _pantry_db


def get_recipe_db() -> Database:
    global _recipe_db
    if _recipe_db is None:
        _recipe_db = Database(
            settings.recipes_db_path, name="recipes", schema_path=SCHEMA_DIR / "recipes.sql"
        )
    return _recipe_db


def get_user_db() -> Database:
    global _user_db
    if _user_db is None:
        _user_db = Database(
            settings.user_intelligence_db_path,
            name="user_intelligence",
            schema_path=SCHEMA_DIR / "user_intelligence.sql",
        )
    return _user_db


async def close_all() -> None:
    """Closes every open singleton connection and drops them, so the
    next get_*_db() call builds a fresh Database."""
    global _pantry_db, _recipe_db, _user_db
    for db in (_pantry_db, _recipe_db, _user_db):
        if db is not None:
            await db.close()
    _pantry_db = None
    _recipe_db = None
    _user_db = None
