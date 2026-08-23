#!/usr/bin/env python3
"""Loads mealsight/seed/data/nutrition_data.json into recipes.db's
nutrition_reference table, then prints a coverage report against whatever
recipes are currently ingested.

Coverage matching is deliberately simple: ingredient names are compared
case-insensitively with whitespace collapsed, and nothing more — no
synonym resolution, no fuzzy matching. That's a data-curation script's
job to expose gaps, not a matching algorithm's job to paper over them;
resolving a recipe ingredient name to a nutrition row for real use is
matching logic, out of scope for this seed pipeline.

Idempotent: every row is written with INSERT OR REPLACE keyed on
ingredient (nutrition_reference's own primary key), so re-running loads
the exact same rows rather than duplicating anything.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from importlib import resources
from typing import Any

from mealsight.db import Database, get_recipe_db
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.seed.load_nutrition")


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def load_nutrition_entries() -> dict[str, dict[str, float]]:
    data_text = resources.files("mealsight.seed").joinpath("data", "nutrition_data.json").read_text()
    payload = json.loads(data_text)
    ingredients: dict[str, dict[str, float]] = payload["ingredients"]
    return {_normalize(name): values for name, values in ingredients.items()}


async def load_nutrition(db: Database | None = None) -> int:
    """Loads every entry from nutrition_data.json. Returns the row count."""
    owns_db = db is None
    db = db or get_recipe_db()

    entries = load_nutrition_entries()
    for ingredient, values in entries.items():
        await db.execute(
            """
            INSERT OR REPLACE INTO nutrition_reference (
                ingredient, calories_per_100g, protein_per_100g, carbs_per_100g,
                fat_per_100g, fiber_per_100g, sodium_per_100g, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ingredient,
                values["calories"], values["protein"], values["carbs"],
                values["fat"], values["fiber"], values["sodium"],
                "usda_fdc_reference",
            ),
        )

    logger.info("nutrition_loaded", count=len(entries))
    if owns_db:
        await db.close()
    return len(entries)


async def compute_ingredient_frequencies(db: Database) -> Counter[str]:
    rows = await db.fetch_all("SELECT ingredients FROM recipes")
    counter: Counter[str] = Counter()
    for row in rows:
        ingredients: list[dict[str, Any]] = json.loads(row["ingredients"])
        distinct_names = {_normalize(item["name"]) for item in ingredients}
        for name in distinct_names:
            counter[name] += 1
    return counter


async def coverage_report(db: Database | None = None) -> dict[str, Any]:
    """Computes what fraction of distinct recipe ingredients have a
    nutrition_reference row, and the top 20 most common uncovered ones."""
    owns_db = db is None
    db = db or get_recipe_db()

    frequencies = await compute_ingredient_frequencies(db)
    covered_rows = await db.fetch_all("SELECT ingredient FROM nutrition_reference")
    covered = {row["ingredient"] for row in covered_rows}

    distinct_total = len(frequencies)
    covered_count = sum(1 for name in frequencies if name in covered)
    coverage_pct = (covered_count / distinct_total * 100) if distinct_total else 0.0

    uncovered = [(name, count) for name, count in frequencies.items() if name not in covered]
    uncovered.sort(key=lambda item: (-item[1], item[0]))
    top_uncovered = uncovered[:20]

    report = {
        "distinct_ingredients": distinct_total,
        "covered": covered_count,
        "coverage_pct": round(coverage_pct, 1),
        "top_uncovered": top_uncovered,
    }
    if owns_db:
        await db.close()
    return report


def print_coverage_report(report: dict[str, Any]) -> None:
    print()
    print(
        f"Nutrition coverage: {report['covered']}/{report['distinct_ingredients']} "
        f"distinct recipe ingredients ({report['coverage_pct']}%)"
    )
    if report["top_uncovered"]:
        print("Top uncovered ingredients by frequency:")
        for name, count in report["top_uncovered"]:
            print(f"  {count:4d}  {name}")
    print()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db = get_recipe_db()
    await load_nutrition(db)
    report = await coverage_report(db)
    print_coverage_report(report)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
