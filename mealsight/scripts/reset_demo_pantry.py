#!/usr/bin/env python3
"""Resets the pantry table to the known demo state in test_data/demo_pantry.json,
so every evaluation run (and anyone cloning the repo) starts from identical
pantry conditions. Makes no API calls: the fixture holds the saved vision
output for the demo photos plus a hand-written list of pantry staples.

Procedure (the one adopted after the Phase 8.5 data loss):
  1. refuses to run while uvicorn or any mealsight MCP subprocess is alive
     (a live process can flush stale WAL state over the file),
  2. copies data/pantry.db to data/backups/ and checks the MD5 of the copy,
  3. empties the pantry table, runs a WAL checkpoint (TRUNCATE) so no stale
     -wal/-shm content survives, then loads the fixture through the real
     update_pantry merge,
  4. prints the resulting row count.

Items seen in several photos are one fridge photographed from several
angles, so they are collapsed to a single entry (largest quantity) rather
than summed. Every row gets added_date = now, so days_remaining equals the
shelf-life estimate and no item starts out expiring or expired.

Only the pantry table is touched; grocery_lists, consumption_log, waste_log
and user_intelligence.db are left as they are.

Run from the backend directory:
    PYTHONPATH=. .venv/bin/python ../scripts/reset_demo_pantry.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "test_data" / "demo_pantry.json"
BACKUP_DIR = REPO_ROOT / "data" / "backups"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - integrity check, not security


def _live_processes() -> list[str]:
    found: list[str] = []
    for pattern in ("uvicorn", "mealsight.mcp_servers"):
        try:
            result = subprocess.run(["pgrep", "-fl", pattern], capture_output=True, text=True, check=False)
        except FileNotFoundError:  # a minimal container has no pgrep (and no other processes to guard against)
            continue
        found.extend(line for line in result.stdout.splitlines() if "reset_demo_pantry" not in line)
    return found


async def _reset() -> int:
    from mealsight.config.settings import settings
    from mealsight.db import close_all, get_pantry_db, get_recipe_db
    from mealsight.matching.normalize import normalize_ingredient
    from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
    from mealsight.pantry.models import PantryItemInput
    from mealsight.pantry.update import update_pantry

    from mealsight.db.init import init_all_databases
    from mealsight.seed.load_shelf_life import load_shelf_life

    live = _live_processes()
    if live:
        print("Refusing to reset while these are running (kill them first):", *live, sep="\n  ")
        return 1

    # A fresh checkout (CI, a new clone) has no database files at all. Applying the schemas is idempotent
    # and touches no existing rows, so this is a no-op on a machine that already has them.
    Path(settings.pantry_db_path).parent.mkdir(parents=True, exist_ok=True)
    await init_all_databases()
    # Shelf-life estimates come from the pantry database's own reference table, which a fresh checkout does
    # not have. Reloading it from the committed JSON is an idempotent INSERT OR REPLACE.
    await load_shelf_life(get_pantry_db())

    db_path = Path(settings.pantry_db_path)
    if db_path.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"pantry.pre_reset_{datetime.now():%Y%m%d_%H%M%S}.db"
        shutil.copy2(db_path, backup)
        if _md5(db_path) != _md5(backup):
            print("Backup checksum mismatch; aborting without changes.")
            return 1
        print(f"Backed up to {backup}")

    fixture = json.loads(FIXTURE.read_text())
    synonyms = await load_synonym_map(get_recipe_db())
    merged: dict[str, PantryItemInput] = {}
    for items in [*fixture["photos"].values(), fixture["staples"]]:
        for raw in items:
            item = PantryItemInput(**raw)
            key = resolve_canonical(normalize_ingredient(item.name), synonyms)
            kept = merged.get(key)
            if kept is None or (item.quantity or 0.0) > (kept.quantity or 0.0):
                merged[key] = item

    pantry_db = get_pantry_db()
    await pantry_db.execute("DELETE FROM pantry")
    await pantry_db.execute("DELETE FROM sqlite_sequence WHERE name = 'pantry'")
    await pantry_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result = await update_pantry(list(merged.values()), pantry_db=pantry_db, synonym_map=synonyms)
    print(f"Pantry reset: {result.added_count} rows from {len(fixture['photos'])} photos + "
          f"{len(fixture['staples'])} staples (fixture: {FIXTURE.name}).")
    await pantry_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await close_all()  # every singleton, including the user database that schema init opened
    return 0


if __name__ == "__main__":
    code = asyncio.run(_reset())
    sys.stdout.flush()
    sys.exit(code)
