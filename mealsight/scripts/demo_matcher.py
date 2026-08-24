#!/usr/bin/env python3
"""Runs the ingredient matcher against real seeded recipes with a
realistic pantry, once with no dietary restrictions and once with
dietary_restrictions=["dairy_free"], printing both so the difference in
behavior is visible side by side.

Run with:
    backend/.venv/bin/python3 scripts/demo_matcher.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import json  # noqa: E402

from mealsight.db import Database, close_all, get_recipe_db  # noqa: E402
from mealsight.matching import MatchResult, build_match_context, match_recipe_by_id  # noqa: E402
from mealsight.matching.normalize import normalize_ingredient  # noqa: E402

PANTRY = [
    "eggs", "rice", "soy sauce", "garlic", "onion", "spinach",
    "chicken thighs", "olive oil", "butter", "milk",
]

RECIPE_COUNT = 5


async def _pick_recipes_with_pantry_overlap(db: Database, count: int) -> list[dict[str, str]]:
    """Picks `count` recipes ranked by how many of their own ingredients
    normalize to something already in PANTRY, so the demo actually
    exercises matched/substitutable/missing rather than showing five
    recipes that share almost nothing with this pantry by pure chance of
    insertion order."""
    pantry_normalized = {normalize_ingredient(item) for item in PANTRY}
    rows = await db.fetch_all("SELECT id, name, ingredients FROM recipes")

    scored: list[tuple[int, dict[str, str]]] = []
    for row in rows:
        names = [item["name"] for item in json.loads(row["ingredients"])]
        overlap = sum(1 for name in names if normalize_ingredient(name) in pantry_normalized)
        scored.append((overlap, {"id": row["id"], "name": row["name"]}))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [recipe for _overlap, recipe in scored[:count]]


def _print_result(recipe_name: str, result: MatchResult) -> None:
    print(f"  score={result.match_score:<6} can_cook={result.can_cook!s:<5} {result.summary}")
    if result.substitutable_items:
        for item in result.substitutable_items:
            print(
                f"    substitution: {item.substitute} for {item.original} "
                f"(ratio {item.ratio}, {item.flavor_impact})"
            )
    if result.partial_matches:
        for item in result.partial_matches:
            print(f"    partial (less specific): {item.pantry_match} for {item.name}")
    if result.missing_items:
        names = ", ".join(f"{item.name}({item.importance})" for item in result.missing_items)
        print(f"    missing: {names}")


async def main() -> None:
    db: Database = get_recipe_db()
    try:
        context = await build_match_context(db)
        rows = await _pick_recipes_with_pantry_overlap(db, RECIPE_COUNT)

        print("=" * 70)
        print("NO DIETARY RESTRICTIONS")
        print("=" * 70)
        unrestricted_results = {}
        for row in rows:
            result = await match_recipe_by_id(db, row["id"], PANTRY, context=context)
            unrestricted_results[row["id"]] = result
            print(f"{row['name']}")
            _print_result(row["name"], result)
            print()

        print("=" * 70)
        print("dietary_restrictions=['dairy_free']")
        print("=" * 70)
        for row in rows:
            restricted = await match_recipe_by_id(
                db, row["id"], PANTRY, dietary_restrictions=["dairy_free"], context=context
            )
            print(f"{row['name']}")
            _print_result(row["name"], restricted)

            unrestricted = unrestricted_results[row["id"]]
            if restricted.model_dump() != unrestricted.model_dump():
                print("    DIFF from unrestricted run:")
                print(f"      unrestricted: score={unrestricted.match_score} can_cook={unrestricted.can_cook}")
                print(f"      dairy_free:   score={restricted.match_score} can_cook={restricted.can_cook}")
            else:
                print("    (no difference from unrestricted run)")
            print()
    finally:
        await close_all()


if __name__ == "__main__":
    asyncio.run(main())
