"""Schema initialization for MealSight's three databases.

init_database() / init_all_databases() are idempotent — every schema file
under mealsight/db/schema/ uses CREATE TABLE IF NOT EXISTS and CREATE
INDEX IF NOT EXISTS throughout, so applying a schema against an
already-initialized database is a no-op, not an error.
"""

from __future__ import annotations

from pathlib import Path

from mealsight.db.connection import Database, get_pantry_db, get_recipe_db, get_user_db
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.db.init")


async def init_database(db: Database, schema_path: Path) -> None:
    sql = schema_path.read_text()
    await db.executescript(sql)

    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    logger.info("database_initialized", db=db.name, tables=[row["name"] for row in tables])


async def init_all_databases() -> None:
    for db in (get_pantry_db(), get_recipe_db(), get_user_db()):
        await init_database(db, db.schema_path)


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
