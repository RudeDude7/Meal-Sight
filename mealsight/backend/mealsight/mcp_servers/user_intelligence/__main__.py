#!/usr/bin/env python3
"""Runs the user-intelligence MCP server over stdio.

Run with (from backend/):
    uv run python -m mealsight.mcp_servers.user_intelligence
or, once installed, via the console script:
    mealsight-user-server

stdio transport uses stdout exclusively for MCP protocol frames. This
module never prints anything itself, and mealsight.utils.logging is
configured to log to stderr specifically so a stray log line during a
request can never corrupt the stream (see that module's
configure_logging) — the show_banner=False below is an extra guard on
top of that, not a substitute for it.
"""

from __future__ import annotations

import asyncio

from mealsight.db import close_all, get_user_db
from mealsight.mcp_servers.user_intelligence.server import mcp
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.user_intelligence.main")


async def _verify_database_reachable() -> None:
    """Opens the real database connection now, at startup, rather than
    lazily on the first tool call. Unlike recipe_engine's recipes table
    or pantry_manager's shelf_life_reference, every table this server
    touches (user_profile, meal_history, preference_scores,
    cooking_patterns) is legitimately empty the first time this server
    ever runs — there is no seed step for a per-user profile — so there
    is nothing to warn about here, only a confirmation that the
    connection itself actually works before serving any requests."""
    db = get_user_db()
    row = await db.fetch_one("SELECT COUNT(*) as count FROM meal_history")
    count = row["count"] if row else 0
    logger.info("user_intelligence_db_verified", meal_history_rows=count)


async def _run() -> None:
    await _verify_database_reachable()
    try:
        await mcp.run_stdio_async(show_banner=False)
    finally:
        await close_all()


def main() -> None:
    """Synchronous entry point — what pyproject.toml's [project.scripts]
    `mealsight-user-server` command points at, since console script
    entry points call a plain callable, not a coroutine."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
