#!/usr/bin/env python3
"""Initializes MealSight's three SQLite databases (pantry, recipes,
user_intelligence) and prints a summary of what exists afterward.

Safe to run repeatedly — schema application is idempotent (every CREATE
statement is IF NOT EXISTS). Pass --reset to wipe all three databases and
reapply their schemas from scratch instead; this requires typed
confirmation since it's destructive and irreversible.

Run with:
    backend/.venv/bin/python3 scripts/init_databases.py
    backend/.venv/bin/python3 scripts/init_databases.py --reset
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mealsight.db import (  # noqa: E402
    Database,
    close_all,
    get_pantry_db,
    get_recipe_db,
    get_user_db,
    init_all_databases,
    reset_database,
)

RESET_CONFIRMATION_TEXT = "RESET"


async def _summarize(databases: list[Database]) -> list[tuple[str, str, str, int]]:
    summary: list[tuple[str, str, str, int]] = []
    for db in databases:
        tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        table_names = ", ".join(row["name"] for row in tables)
        size_bytes = db.path.stat().st_size if db.path.exists() else 0
        summary.append((db.name, str(db.path), table_names, size_bytes))
    return summary


def _print_summary(summary: list[tuple[str, str, str, int]]) -> None:
    name_width = max(len(row[0]) for row in summary) + 2
    path_width = max(len(row[1]) for row in summary) + 2
    size_width = 10

    print()
    print(f"{'DATABASE':<{name_width}}{'PATH':<{path_width}}{'SIZE':<{size_width}}TABLES")
    print("-" * (name_width + path_width + size_width + 40))
    for name, path, tables, size_bytes in summary:
        size_str = f"{size_bytes:,}B"
        print(f"{name:<{name_width}}{path:<{path_width}}{size_str:<{size_width}}{tables}")
    print()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="wipe all three databases and reapply their schemas from scratch (destructive)",
    )
    args = parser.parse_args()

    databases = [get_pantry_db(), get_recipe_db(), get_user_db()]

    try:
        if args.reset:
            print("This will DROP EVERY TABLE in all three databases:")
            for db in databases:
                print(f"  - {db.name}: {db.path}")
            typed = input(f"Type {RESET_CONFIRMATION_TEXT!r} to confirm: ")
            if typed != RESET_CONFIRMATION_TEXT:
                print("Aborted — confirmation text did not match. Nothing was changed.")
                return 1
            for db in databases:
                await reset_database(db, confirm=True)
            print("Reset complete.")
        else:
            await init_all_databases()
            print("Initialization complete.")

        summary = await _summarize(databases)
        _print_summary(summary)
    finally:
        await close_all()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
