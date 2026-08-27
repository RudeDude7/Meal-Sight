"""Schema initialization for MealSight's three databases.

init_database() / init_all_databases() are idempotent — every schema file
under mealsight/db/schema/ uses CREATE TABLE IF NOT EXISTS and CREATE
INDEX IF NOT EXISTS throughout, so applying a schema against an
already-initialized database is a no-op, not an error. This is exactly
what makes it safe to call on every single server startup (see each MCP
server's own __main__.py), not just once during a manual deploy step:
a restart re-applies the identical schema, creates nothing new, and
touches zero existing rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mealsight.db.connection import Database, get_pantry_db, get_recipe_db, get_user_db
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.db.init")


@dataclass(slots=True, frozen=True)
class SchemaInitResult:
    """Which tables init_database actually created this call versus
    which ones were already there — the two are meaningfully different
    events (a genuinely fresh database directory versus an ordinary
    restart against one that already exists), and a caller logging
    "database initialized" with no further detail can't tell them apart
    after the fact."""

    created_tables: list[str]
    existing_tables: list[str]


async def _table_names(db: Database) -> list[str]:
    rows = await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return [row["name"] for row in rows]


async def init_database(db: Database, schema_path: Path) -> SchemaInitResult:
    before = set(await _table_names(db))

    sql = schema_path.read_text()
    await db.executescript(sql)

    after = await _table_names(db)
    created = sorted(set(after) - before)
    existing = sorted(before)

    logger.info(
        "database_initialized", db=db.name, created_tables=created, existing_tables=existing
    )
    return SchemaInitResult(created_tables=created, existing_tables=existing)


async def init_all_databases() -> dict[str, SchemaInitResult]:
    results: dict[str, SchemaInitResult] = {}
    for db in (get_pantry_db(), get_recipe_db(), get_user_db()):
        results[db.name] = await init_database(db, db.schema_path)
    return results


async def reset_database(db: Database, *, confirm: bool = False) -> None:
    """Drops every table in db and reapplies its schema from scratch.

    Meant for test fixtures and local development only — refuses to run
    unless confirm=True is passed explicitly, since this is a destructive,
    irreversible operation and a default-on footgun is exactly what
    confirm=False as the default is meant to prevent.
    """
    if not confirm:
        raise ValueError(
            f"reset_database({db.name!r}) refused: this drops every table and requires confirm=True"
        )

    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    async with db.transaction() as connection:
        for row in tables:
            # Table names here come from sqlite_master itself, never from
            # caller- or user-supplied input, so interpolating the name is
            # safe — SQL has no bind-parameter placeholder for identifiers,
            # only for values, so this is the only way to express it at all.
            await connection.execute(f"DROP TABLE IF EXISTS {row['name']}")

    await init_database(db, db.schema_path)
