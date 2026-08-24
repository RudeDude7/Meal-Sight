#!/usr/bin/env python3
"""Loads mealsight/seed/data/nutrition_data.json into recipes.db's
nutrition_reference table, then prints a coverage report against both
populations that actually need nutrition data: the seeded recipe corpus,
and the vision model's own ingredient vocabulary (see
mealsight.seed.vision_vocabulary).

Coverage matching resolves each ingredient name exactly the way a real
lookup would: normalize with mealsight.matching.normalize.
normalize_ingredient, then resolve through ingredient_synonyms with
mealsight.matching.synonyms.resolve_canonical, then check for a
nutrition_reference row under that canonical name. Earlier versions of
this module skipped the synonym-resolution step, which quietly measured
the wrong thing twice over: it let "Chopped onion" and "onion" count as
two different ingredients before the normalizer fix, and separately it
let a nutrition row filed under the wrong key (a "scallion" entry that
should have been "green onion", the synonym table's actual canonical
target) go undetected as broken, because the coverage check never
exercised synonym resolution the way real nutrition lookups do.

Idempotent: every row is written with INSERT OR REPLACE keyed on
ingredient (nutrition_reference's own primary key), so re-running loads
the exact same rows rather than duplicating anything.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Mapping
from importlib import resources
from typing import Any

from mealsight.db import Database, get_recipe_db
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.seed.vision_vocabulary import (
    VISION_BENCHMARK_CHECKPOINT_PATH,
    extract_vision_ingredient_names,
)
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.seed.load_nutrition")

# Occurrence counts below this are grouped into a single low-frequency
# bucket for the distribution report — see coverage_report's
# "uncovered_distribution" key.
_DISTRIBUTION_BUCKETS: tuple[tuple[str, int], ...] = (("5+", 5), ("3-4", 3), ("2", 2), ("1", 1))


def load_nutrition_entries() -> dict[str, dict[str, float]]:
    data_text = resources.files("mealsight.seed").joinpath("data", "nutrition_data.json").read_text()
    payload = json.loads(data_text)
    ingredients: dict[str, dict[str, float]] = payload["ingredients"]
    return {normalize_ingredient(name): values for name, values in ingredients.items()}


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
        distinct_names = {normalize_ingredient(item["name"]) for item in ingredients}
        for name in distinct_names:
            counter[name] += 1
    return counter


def _bucket_for_count(count: int) -> str:
    for label, minimum in _DISTRIBUTION_BUCKETS:
        if count >= minimum:
            return label
    return "1"  # unreachable given the buckets above end at 1, kept for exhaustiveness


def _build_coverage_report(
    raw_name_frequencies: Counter[str],
    synonym_map: Mapping[str, str],
    covered: set[str],
) -> dict[str, Any]:
    """Shared core for both coverage_report and
    vision_vocabulary_coverage_report: takes a Counter of raw (not yet
    normalized) ingredient-name strings to how often each occurred,
    resolves each to its canonical form (normalize, then synonym
    resolution — the same path a real nutrition lookup takes), and
    reports coverage both by distinct canonical ingredient and by total
    occurrences."""
    canonical_frequencies: Counter[str] = Counter()
    for raw_name, count in raw_name_frequencies.items():
        normalized = normalize_ingredient(raw_name)
        if not normalized:
            continue
        canonical = resolve_canonical(normalized, synonym_map)
        canonical_frequencies[canonical] += count

    distinct_total = len(canonical_frequencies)
    covered_count = sum(1 for name in canonical_frequencies if name in covered)
    coverage_pct = (covered_count / distinct_total * 100) if distinct_total else 0.0

    total_occurrences = sum(canonical_frequencies.values())
    covered_occurrences = sum(
        count for name, count in canonical_frequencies.items() if name in covered
    )
    weighted_coverage_pct = (
        (covered_occurrences / total_occurrences * 100) if total_occurrences else 0.0
    )

    uncovered = [
        (name, count) for name, count in canonical_frequencies.items() if name not in covered
    ]
    uncovered.sort(key=lambda item: (-item[1], item[0]))

    distribution: Counter[str] = Counter()
    for _name, count in uncovered:
        distribution[_bucket_for_count(count)] += 1

    return {
        "distinct_ingredients": distinct_total,
        "covered": covered_count,
        "coverage_pct": round(coverage_pct, 1),
        "total_occurrences": total_occurrences,
        "covered_occurrences": covered_occurrences,
        "weighted_coverage_pct": round(weighted_coverage_pct, 1),
        "uncovered": uncovered,
        "uncovered_distribution": dict(distribution),
        "top_uncovered": uncovered[:20],
    }


async def coverage_report(db: Database | None = None) -> dict[str, Any]:
    """Computes nutrition_reference coverage against every distinct
    ingredient name appearing in the ingested recipes (the recipe-corpus
    population), two ways:

    - distinct coverage: what fraction of distinct canonical ingredient
      names have a nutrition_reference row at all.
    - occurrence-weighted coverage: what fraction of total ingredient
      *occurrences* across every recipe are covered — an ingredient used
      in 40 recipes counts 40 times as much as one used in a single
      recipe, since that's what actually determines how many recipes'
      nutrition totals (mealsight's calculate_nutrition) would be
      silently understated by a missing row.

    See vision_vocabulary_coverage_report for the second population this
    application actually needs covered: ingredient names the vision model
    itself produces, which never appear in TheMealDB at all.
    """
    owns_db = db is None
    db = db or get_recipe_db()

    frequencies = await compute_ingredient_frequencies(db)
    synonym_map = await load_synonym_map(db)
    covered_rows = await db.fetch_all("SELECT ingredient FROM nutrition_reference")
    covered = {row["ingredient"] for row in covered_rows}

    report = _build_coverage_report(frequencies, synonym_map, covered)
    if owns_db:
        await db.close()
    return report


async def vision_vocabulary_coverage_report(
    db: Database | None = None, raw_vision_names: Counter[str] | None = None
) -> dict[str, Any]:
    """The same coverage computation as coverage_report, but against the
    vision model's own ingredient vocabulary instead of the recipe
    corpus — see mealsight.seed.vision_vocabulary for where that
    vocabulary comes from and why it's a genuinely different population
    to check.

    raw_vision_names defaults to parsing the real checkpointed benchmark
    output on disk; pass it explicitly to check a specific set instead
    (what the test suite does, since the real checkpoint file is
    gitignored and won't exist on every machine).
    """
    owns_db = db is None
    db = db or get_recipe_db()

    if raw_vision_names is None:
        raw_vision_names = extract_vision_ingredient_names()
    synonym_map = await load_synonym_map(db)
    covered_rows = await db.fetch_all("SELECT ingredient FROM nutrition_reference")
    covered = {row["ingredient"] for row in covered_rows}

    report = _build_coverage_report(raw_vision_names, synonym_map, covered)
    if owns_db:
        await db.close()
    return report


def print_coverage_report(report: dict[str, Any], label: str = "recipe corpus") -> None:
    print()
    print(
        f"Nutrition coverage [{label}] (distinct): {report['covered']}/{report['distinct_ingredients']} "
        f"distinct ingredients ({report['coverage_pct']}%)"
    )
    print(
        f"Nutrition coverage [{label}] (occurrence-weighted): "
        f"{report['covered_occurrences']}/{report['total_occurrences']} "
        f"ingredient occurrences ({report['weighted_coverage_pct']}%)"
    )
    if report["uncovered_distribution"]:
        dist = report["uncovered_distribution"]
        print(
            "Uncovered distribution — "
            f"5+ occurrences: {dist.get('5+', 0)}, "
            f"3-4 occurrences: {dist.get('3-4', 0)}, "
            f"2 occurrences: {dist.get('2', 0)}, "
            f"1 occurrence: {dist.get('1', 0)}"
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
    print_coverage_report(report, label="recipe corpus")

    if VISION_BENCHMARK_CHECKPOINT_PATH.exists():
        vision_report = await vision_vocabulary_coverage_report(db)
        print_coverage_report(vision_report, label="vision vocabulary")
    else:
        print(
            "(skipping vision-vocabulary coverage — no checkpoint at "
            f"{VISION_BENCHMARK_CHECKPOINT_PATH})"
        )

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
