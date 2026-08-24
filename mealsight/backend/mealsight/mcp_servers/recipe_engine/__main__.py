#!/usr/bin/env python3
"""Runs the recipe-engine MCP server over stdio.

Run with (from backend/):
    uv run python -m mealsight.mcp_servers.recipe_engine
or, once installed, via the console script:
    mealsight-recipe-server

stdio transport uses stdout exclusively for MCP protocol frames. This
module never prints anything itself, and mealsight.utils.logging is
configured to log to stderr specifically so a stray log line during a
request can never corrupt the stream (see that module's
configure_logging) — the show_banner=False below is an extra guard on
top of that, not a substitute for it.
"""

from __future__ import annotations

import asyncio

from mealsight.db import close_all, get_recipe_db
from mealsight.mcp_servers.recipe_engine.server import mcp
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.recipe_engine.main")


async def _verify_recipes_seeded() -> None:
    """Opens the real database connection now, at startup, rather than
    lazily on the first tool call, and logs a loud warning if the
    recipes table is empty — a server answering search_recipes against
    zero rows would otherwise silently look "working" while being
    useless."""
    db = get_recipe_db()
    row = await db.fetch_one("SELECT COUNT(*) as count FROM recipes")
    count = row["count"] if row else 0
    if count == 0:
        logger.warning(
            "recipes_table_empty",
            message="recipes table has 0 rows — run `mealsight-seed` before serving requests",
        )
    else:
        logger.info("recipes_table_verified", recipe_count=count)


async def _run() -> None:
    await _verify_recipes_seeded()
    try:
        await mcp.run_stdio_async(show_banner=False)
    finally:
        await close_all()


def main() -> None:
    """Synchronous entry point — what pyproject.toml's [project.scripts]
    `mealsight-recipe-server` command points at, since console script
    entry points call a plain callable, not a coroutine."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
