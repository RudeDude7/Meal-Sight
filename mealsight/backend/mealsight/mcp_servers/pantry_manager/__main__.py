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

from mealsight.db import close_all, get_pantry_db
from mealsight.mcp_servers.pantry_manager.server import mcp
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.pantry_manager.main")


async def _verify_shelf_life_seeded() -> None:
    """Opens the real database connection now, at startup, rather than
    lazily on the first tool call, and logs a loud warning if
    shelf_life_reference is empty — unlike the pantry table itself
    (which legitimately starts empty), an empty shelf_life_reference
    means update_pantry/flag_expiring would silently fall back to
    category-default shelf lives for every single item."""
    db = get_pantry_db()
    row = await db.fetch_one("SELECT COUNT(*) as count FROM shelf_life_reference")
    count = row["count"] if row else 0
    if count == 0:
        logger.warning(
            "shelf_life_reference_empty",
            message="shelf_life_reference has 0 rows — run `mealsight-seed` before serving requests",
        )
    else:
        logger.info("shelf_life_reference_verified", row_count=count)


async def _run() -> None:
    await _verify_shelf_life_seeded()
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
