#!/usr/bin/env python3
"""Runs the pantry-manager MCP server over stdio.

Run with (from backend/):
    uv run python -m mealsight.mcp_servers.pantry_manager
or, once installed, via the console script:
    mealsight-pantry-server

stdio transport uses stdout exclusively for MCP protocol frames. This
module never prints anything itself, and mealsight.utils.logging is
configured to log to stderr specifically so a stray log line during a
request can never corrupt the stream (see that module's
configure_logging) — the show_banner=False below is an extra guard on
top of that, not a substitute for it.
"""

from __future__ import annotations

import asyncio

from mealsight.db import close_all, get_pantry_db, init_database
from mealsight.mcp_servers.pantry_manager.server import mcp
from mealsight.seed.load_shelf_life import load_shelf_life
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.pantry_manager.main")


async def _initialize_schema() -> None:
    """Applies pantry.sql against the real database, at startup, before
    serving any request — idempotent (CREATE TABLE IF NOT EXISTS
    throughout), so this runs unconditionally on every boot, including
    the very first one against a completely fresh database directory."""
    db = get_pantry_db()
    result = await init_database(db, db.schema_path)
    logger.info(
        "pantry_manager_schema_ready",
        created_tables=result.created_tables,
        existing_tables=result.existing_tables,
    )


async def _seed_shelf_life_reference() -> None:
    """Loads mealsight/seed/data/shelf_life.json into shelf_life_reference
    unconditionally, every startup — unlike recipe_engine's own recipe
    seeding (mealsight-seed, a real network call to TheMealDB), this is
    a small LOCAL bundled file with no network involved at all, so
    there's no real cost to re-running it every boot, and doing so
    means shelf_life_reference is never the one seed table an operator
    has to remember to populate separately. INSERT OR REPLACE keyed on
    each entry's own normalized name makes this idempotent: a restart
    with already-populated data touches the same rows with the same
    values, not duplicates."""
    row_count = await load_shelf_life(get_pantry_db())
    logger.info("shelf_life_reference_seeded", row_count=row_count)


async def _run() -> None:
    await _initialize_schema()
    await _seed_shelf_life_reference()
    try:
        await mcp.run_stdio_async(show_banner=False)
    finally:
        await close_all()


def main() -> None:
    """Synchronous entry point — what pyproject.toml's [project.scripts]
    `mealsight-pantry-server` command points at, since console script
    entry points call a plain callable, not a coroutine."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
