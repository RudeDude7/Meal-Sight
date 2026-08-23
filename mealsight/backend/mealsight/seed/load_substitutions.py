#!/usr/bin/env python3
"""Loads mealsight/seed/data/substitutions.json into recipes.db's
substitutions table.

Idempotent: every row is written with INSERT OR REPLACE keyed on the
table's own composite primary key (original_ingredient, substitute), so
re-running loads the same rows rather than duplicating them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from importlib import resources

from mealsight.db import Database, get_recipe_db
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.seed.load_substitutions")


def load_substitution_entries() -> list[dict[str, str]]:
    data_text = resources.files("mealsight.seed").joinpath("data", "substitutions.json").read_text()
    payload = json.loads(data_text)
    entries: list[dict[str, str]] = payload["substitutions"]
    return entries


async def load_substitutions(db: Database | None = None) -> int:
    owns_db = db is None
    db = db or get_recipe_db()

    entries = load_substitution_entries()
    for entry in entries:
        await db.execute(
            """
            INSERT OR REPLACE INTO substitutions (
                original_ingredient, substitute, ratio, flavor_impact, dietary_notes, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["original_ingredient"], entry["substitute"], entry.get("ratio", "1:1"),
                entry.get("flavor_impact"), entry.get("dietary_notes", ""), entry.get("notes"),
            ),
        )

    logger.info("substitutions_loaded", count=len(entries))
    if owns_db:
        await db.close()
    return len(entries)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = asyncio.run(load_substitutions())
    print(f"Loaded {count} substitutions.")
