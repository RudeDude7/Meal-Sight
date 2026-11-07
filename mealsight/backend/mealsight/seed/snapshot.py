"""A pinned, offline snapshot of the recipe corpus.

recipes.db is gitignored and its rows come from the live TheMealDB API (seed.recipes_from_mealdb), so a fresh
checkout cannot rebuild the SAME corpus: the API can change, and the live database has had rows corrected
since it was fetched. That matters because the Dimension 3 expectations were derived by hand from these exact
recipes. Continuous integration therefore loads this committed snapshot instead of calling the API.

The snapshot carries a content digest of its own rows. Loading verifies it, so a hand edit or a truncated file
fails loudly instead of silently changing what the tests measure.

Regenerate (only when the corpus is meant to change, and then re-derive the Dimension 3 expectations and
update eval/baseline/baseline.json in the same change):

    uv run python -m mealsight.seed.snapshot export
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

from mealsight.db import Database, get_recipe_db, init_database

SNAPSHOT_RESOURCE = ("data", "recipes_snapshot.json")
RECIPE_COLUMNS = (
    "id", "name", "cuisine", "meal_type", "cook_time_minutes", "cook_time_source", "prep_time_minutes",
    "difficulty", "servings_base", "dietary_tags", "ingredients", "steps", "image_url", "source",
    "times_recommended", "average_rating",
)  # fmt: skip


def snapshot_path() -> Path:
    return Path(str(resources.files("mealsight.seed").joinpath(*SNAPSHOT_RESOURCE)))


def digest_rows(rows: list[dict[str, Any]]) -> str:
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


async def export_snapshot(db: Database, path: Path | None = None) -> int:
    selected = ", ".join(RECIPE_COLUMNS)
    rows = [
        {column: row[column] for column in RECIPE_COLUMNS}
        for row in await db.fetch_all(f"SELECT {selected} FROM recipes ORDER BY id")  # noqa: S608 - fixed names
    ]
    payload = {
        "_meta": {
            "note": "Pinned copy of recipes.db's recipes table. See mealsight/seed/snapshot.py.",
            "count": len(rows),
            "sha256": digest_rows(rows),
        },
        "recipes": rows,
    }
    (path or snapshot_path()).write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return len(rows)


async def load_snapshot(db: Database, path: Path | None = None) -> int:
    """Loads the snapshot into an initialized recipes database. Idempotent. Returns the row count."""
    payload = json.loads((path or snapshot_path()).read_text())
    rows: list[dict[str, Any]] = payload["recipes"]
    meta = payload["_meta"]
    if len(rows) != meta["count"] or digest_rows(rows) != meta["sha256"]:
        raise ValueError("recipes_snapshot.json does not match its own recorded digest; refusing to load it.")
    columns = {r["name"] for r in await db.fetch_all("PRAGMA table_info(recipes)")}
    if "cook_time_source" not in columns:
        await db.execute("ALTER TABLE recipes ADD COLUMN cook_time_source TEXT")
    placeholders = ", ".join("?" for _ in RECIPE_COLUMNS)
    insert = f"INSERT OR REPLACE INTO recipes ({', '.join(RECIPE_COLUMNS)}) VALUES ({placeholders})"  # noqa: S608
    for row in rows:
        await db.execute(insert, tuple(row[c] for c in RECIPE_COLUMNS))
    return len(rows)


async def _main(action: str) -> int:
    db = get_recipe_db()
    try:
        await init_database(db, db.schema_path)
        if action == "export":
            count = await export_snapshot(db)
            print(f"exported {count} recipes to {snapshot_path()}")
        else:
            print(f"loaded {await load_snapshot(db)} recipes")
    finally:
        await db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "load"])
    return asyncio.run(_main(parser.parse_args().action))


if __name__ == "__main__":
    raise SystemExit(main())
