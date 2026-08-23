#!/usr/bin/env python3
"""Loads mealsight/seed/data/ingredient_synonyms.json into recipes.db's
ingredient_synonyms table.

Idempotent: every row is written with INSERT OR REPLACE keyed on the
table's own composite primary key (canonical_name, synonym), so
re-running loads the same rows rather than duplicating them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from importlib import resources

from mealsight.db import Database, get_recipe_db
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.seed.load_synonyms")


def load_synonym_entries() -> list[dict[str, str]]:
    data_text = resources.files("mealsight.seed").joinpath("data", "ingredient_synonyms.json").read_text()
    payload = json.loads(data_text)
    entries: list[dict[str, str]] = payload["synonyms"]
    return entries


async def load_synonyms(db: Database | None = None) -> int:
    owns_db = db is None
    db = db or get_recipe_db()

    entries = load_synonym_entries()
    for entry in entries:
        await db.execute(
            "INSERT OR REPLACE INTO ingredient_synonyms (canonical_name, synonym) VALUES (?, ?)",
            (entry["canonical_name"], entry["synonym"]),
        )

    logger.info("synonyms_loaded", count=len(entries))
    if owns_db:
        await db.close()
    return len(entries)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = asyncio.run(load_synonyms())
    print(f"Loaded {count} ingredient synonyms.")
