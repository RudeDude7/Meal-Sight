#!/usr/bin/env python3
"""One-off data integrity audit over the seeded recipes.db, run once before
building the ingredient matcher (Phase 2). Prints four reports:

    1. Nutrition coverage — % of distinct recipe ingredients with a
       nutrition_reference row, plus the top 20 uncovered by frequency.
    2. Dietary tag safety — any recipe tagged dairy_free/vegan/gluten_free
       whose own ingredient list contains a term that contradicts the tag.
    3. Cook time sanity — min/max/mean/median of cook_time_minutes, and
       whether one single value dominates (a sign the estimator is falling
       through to its step-count heuristic too often).
    4. Five sample recipes, printed in full.

This script only reads recipes.db. It does not write anything.

Run with:
    backend/.venv/bin/python3 scripts/audit_recipe_data.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio  # noqa: E402

from mealsight.db import Database, close_all, get_recipe_db  # noqa: E402
from mealsight.seed.load_nutrition import coverage_report  # noqa: E402

# Independent of recipe_parsing's own term lists, deliberately — see
# backend/tests/test_seed/test_substitutions_safety.py for the same
# reasoning: a bug in the production term list shouldn't be able to mask
# itself by also being the list the audit checks against.
DAIRY_TERMS = ("milk", "butter", "cream", "cheese", "yogurt", "ghee", "whey", "custard", "buttermilk")
ANIMAL_TERMS = (
    "chicken", "beef", "pork", "lamb", "turkey", "duck", "bacon", "sausage", "ham",
    "shrimp", "prawn", "fish", "salmon", "tuna", "cod", "crab", "lobster", "anchov",
    "gelatin", "lard", "egg", "honey", "milk", "butter", "cream", "cheese", "yogurt",
    "ghee", "whey", "custard", "buttermilk", "mayonnaise",
)
GLUTEN_TERMS = (
    "flour", "bread", "pasta", "noodle", "wheat", "barley", "rye", "couscous",
    "cracker", "beer", "malt", "seitan", "spaghetti", "macaroni", "udon", "ramen",
)


def _ingredient_names(recipe_row: Any) -> list[str]:
    ingredients: list[dict[str, Any]] = json.loads(recipe_row["ingredients"])
    return [item["name"] for item in ingredients]


def _dietary_tags(recipe_row: Any) -> list[str]:
    raw = recipe_row["dietary_tags"]
    tags: list[str] = json.loads(raw) if raw else []
    return tags


def _matches_any(name: str, terms: tuple[str, ...]) -> str | None:
    lowered = name.lower()
    for term in terms:
        if term in lowered:
            return term
    return None


async def audit_nutrition_coverage(db: Database) -> None:
    print("=" * 70)
    print("1. NUTRITION COVERAGE")
    print("=" * 70)
    report = await coverage_report(db)
    print(
        f"Nutrition coverage: {report['covered']}/{report['distinct_ingredients']} "
        f"distinct recipe ingredients ({report['coverage_pct']}%)"
    )
    print("Top 20 uncovered ingredients by frequency:")
    for name, count in report["top_uncovered"]:
        print(f"  {count:4d}  {name}")
    print()


async def audit_dietary_tag_safety(db: Database) -> None:
    print("=" * 70)
    print("2. DIETARY TAG SAFETY")
    print("=" * 70)
    rows = await db.fetch_all("SELECT name, dietary_tags, ingredients FROM recipes")

    checks = [
        ("dairy_free", DAIRY_TERMS),
        ("vegan", ANIMAL_TERMS),
        ("gluten_free", GLUTEN_TERMS),
    ]

    total_violations = 0
    for tag, terms in checks:
        violations: list[tuple[str, str, str]] = []
        for row in rows:
            tags = _dietary_tags(row)
            if tag not in tags:
                continue
            for name in _ingredient_names(row):
                hit = _matches_any(name, terms)
                if hit is not None:
                    violations.append((row["name"], name, hit))

        print(f"[{tag}] {len(violations)} violation(s)")
        for recipe_name, ingredient_name, term in violations:
            print(f"  recipe={recipe_name!r} ingredient={ingredient_name!r} matched_term={term!r}")
        total_violations += len(violations)
    print()
    print(f"Total violations across all three tags: {total_violations}")
    print()


async def audit_cook_time_sanity(db: Database) -> None:
    print("=" * 70)
    print("3. COOK TIME SANITY")
    print("=" * 70)
    rows = await db.fetch_all(
        "SELECT cook_time_minutes FROM recipes WHERE cook_time_minutes IS NOT NULL"
    )
    values = [int(row["cook_time_minutes"]) for row in rows]

    if not values:
        print("No recipes with a non-null cook_time_minutes.")
        print()
        return

    counter = Counter(values)
    most_common_value, most_common_count = counter.most_common(1)[0]
    share = most_common_count / len(values) * 100

    print(f"count:  {len(values)}")
    print(f"min:    {min(values)}")
    print(f"max:    {max(values)}")
    print(f"mean:   {statistics.mean(values):.2f}")
    print(f"median: {statistics.median(values):.2f}")
    print(
        f"most common value: {most_common_value} minutes, "
        f"shared by {most_common_count} recipes ({share:.1f}%)"
    )
    if share > 30:
        print(
            f"FINDING: {share:.1f}% of recipes share a single cook_time_minutes value "
            f"(> 30%) — the heuristic fallback is likely dominating over extracted durations."
        )
    else:
        print(f"OK: {share:.1f}% share is below the 30% threshold.")
    print()


async def audit_sample_recipes(db: Database) -> None:
    print("=" * 70)
    print("4. SAMPLE RECIPES")
    print("=" * 70)
    rows = await db.fetch_all("SELECT name, cook_time_minutes, dietary_tags, ingredients FROM recipes LIMIT 5")
    for row in rows:
        names = _ingredient_names(row)
        print(f"name:             {row['name']}")
        print(f"cook_time_minutes: {row['cook_time_minutes']}")
        print(f"dietary_tags:     {row['dietary_tags']}")
        print(f"ingredients:      {', '.join(names)}")
        print("-" * 70)
    print()


async def main() -> None:
    db = get_recipe_db()
    try:
        await audit_nutrition_coverage(db)
        await audit_dietary_tag_safety(db)
        await audit_cook_time_sanity(db)
        await audit_sample_recipes(db)
    finally:
        await close_all()


if __name__ == "__main__":
    asyncio.run(main())
