#!/usr/bin/env python3
"""Runs every seed loader against recipes.db, in dependency order, and
prints a summary.

Order: recipes first (everything else either has no dependency on it, or
— in nutrition's case — needs it already loaded to compute a meaningful
coverage report against), then synonyms and substitutions (independent
reference tables), then nutrition last.

Every loader is independently idempotent (see each module's own
docstring), so running this more than once is safe and produces the same
row counts, not duplicates.

Run with (from backend/):
    uv run mealsight-seed
(installed as a console script by this package — see pyproject.toml's
[project.scripts] entry.)

If that ever fails with "ModuleNotFoundError: No module named 'mealsight'"
right after a fresh `uv sync`, it's an editable-install/site-packages
metadata glitch, not a code problem — `uv run python -m mealsight.seed.seed_all`
(from backend/) sidesteps it, since -m resolves the package via the
current directory rather than the installed console-script shim. On a
machine where the whole project directory is under active cloud sync
(iCloud Drive's "Desktop & Documents" sync, Dropbox, etc.), that sync
process can intermittently alter newly-written .venv metadata files out
from under an install; `uv sync --reinstall` (or excluding the project's
.venv/.cache from that sync) clears it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from mealsight.db import get_recipe_db
from mealsight.utils.logging import get_logger

from .load_nutrition import coverage_report, load_nutrition, print_coverage_report
from .load_substitutions import load_substitutions
from .load_synonyms import load_synonyms
from .recipes_from_mealdb import run as run_recipe_ingestion

logger = get_logger("mealsight.seed.seed_all")

MIN_RECIPES = 150
MIN_SUBSTITUTIONS = 55
MIN_SYNONYMS = 80
MIN_NUTRITION_ENTRIES = 120


async def _run() -> int:
    warnings: list[str] = []

    db = get_recipe_db()

    print("Seeding recipes from TheMealDB...")
    recipe_count = await run_recipe_ingestion(db)

    print("Loading ingredient synonyms...")
    synonym_count = await load_synonyms(db)

    print("Loading substitutions...")
    substitution_count = await load_substitutions(db)

    print("Loading nutrition reference data...")
    nutrition_count = await load_nutrition(db)
    report = await coverage_report(db)

    if recipe_count < MIN_RECIPES:
        warnings.append(f"only {recipe_count} recipes loaded, target was at least {MIN_RECIPES}")
    if substitution_count < MIN_SUBSTITUTIONS:
        warnings.append(
            f"only {substitution_count} substitutions loaded, target was at least {MIN_SUBSTITUTIONS}"
        )
    if synonym_count < MIN_SYNONYMS:
        warnings.append(f"only {synonym_count} synonyms loaded, target was at least {MIN_SYNONYMS}")
    if nutrition_count < MIN_NUTRITION_ENTRIES:
        warnings.append(
            f"only {nutrition_count} nutrition entries loaded, target was at least {MIN_NUTRITION_ENTRIES}"
        )

    cuisine_rows = await db.fetch_all(
        "SELECT COALESCE(cuisine, '(none)') as cuisine, COUNT(*) as count "
        "FROM recipes GROUP BY cuisine ORDER BY count DESC"
    )

    print()
    print("=" * 60)
    print("SEED SUMMARY")
    print("=" * 60)
    print(f"recipes:              {recipe_count}")
    print(f"substitutions:        {substitution_count}")
    print(f"ingredient_synonyms:  {synonym_count}")
    print(f"nutrition_reference:  {nutrition_count}")
    print()
    print("Recipes by cuisine:")
    for row in cuisine_rows:
        print(f"  {row['count']:4d}  {row['cuisine']}")

    print_coverage_report(report)

    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("No warnings — all targets met.")
    print()

    await db.close()
    return 1 if warnings else 0


def main() -> int:
    """Synchronous entry point — this is what pyproject.toml's
    [project.scripts] `mealsight-seed` command points at, since console
    script entry points call a plain callable, not a coroutine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
