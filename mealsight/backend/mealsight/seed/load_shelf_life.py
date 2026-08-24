#!/usr/bin/env python3
"""Loads mealsight/seed/data/shelf_life.json into pantry.db's
shelf_life_reference table.

Idempotent: every row is written with INSERT OR REPLACE keyed on the
table's own primary key (item_name), so re-running loads the same rows
rather than duplicating them. Keys are normalized with
mealsight.matching.normalize.normalize_ingredient — the same normalizer
mealsight.pantry uses when resolving a pantry item to a shelf-life row —
so "Chicken Breasts" (a raw pantry item name) and "chicken breast" (this
file's key) actually connect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from importlib import resources
from typing import Any

from mealsight.db import Database, get_pantry_db
from mealsight.matching.normalize import normalize_ingredient
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.seed.load_shelf_life")


def load_shelf_life_entries() -> list[dict[str, Any]]:
    data_text = resources.files("mealsight.seed").joinpath("data", "shelf_life.json").read_text()
    payload = json.loads(data_text)
    entries: list[dict[str, Any]] = payload["items"]
    return entries


async def load_shelf_life(db: Database | None = None) -> int:
    """Loads every entry from shelf_life.json. Returns the row count."""
    owns_db = db is None
    db = db or get_pantry_db()

    entries = load_shelf_life_entries()
    for entry in entries:
        await db.execute(
            """
            INSERT OR REPLACE INTO shelf_life_reference (
                item_name, category, shelf_days_refrigerated,
                shelf_days_frozen, shelf_days_pantry
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalize_ingredient(entry["item_name"]),
                entry["category"],
                entry["shelf_days_refrigerated"],
                entry["shelf_days_frozen"],
                entry["shelf_days_pantry"],
            ),
        )

    logger.info("shelf_life_loaded", count=len(entries))
    if owns_db:
        await db.close()
    return len(entries)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = asyncio.run(load_shelf_life())
    print(f"Loaded {count} shelf life entries.")
