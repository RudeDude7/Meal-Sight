"""Guards mealsight.pantry.category.resolve_category's coverage of the
real seeded recipe corpus from silently regressing.

The section-grouping remediation this test protects found that
create_grocery_list originally derived section straight from
shelf_life_reference — a table with only 86 rows against ~483 distinct
recipe-corpus ingredients at the time, so a real grocery list built from
real missing ingredients put 14 of 17 items in OTHER. This test checks
the real thing resolve_category was built to fix: what fraction of
distinct, real recipe-corpus ingredients resolve to a section other than
"other". If a future recipe addition (or a shelf_life.json/keyword-rule
edit) drops that below 90%, this test fails loudly instead of a real
grocery list quietly filling up with OTHER again.

Deliberately checks the real, already-seeded recipes.db and pantry.db —
the same reasoning test_seed/test_nutrition_coverage.py already uses for
checking real data rather than a synthetic fixture. Skips cleanly on a
machine where recipes.db hasn't been seeded yet.
"""

from __future__ import annotations

import json

import pytest

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry.category import resolve_category
from mealsight.pantry.shelf_life import load_shelf_life_map

MIN_SECTION_COVERAGE_PCT = 90.0

pytestmark = pytest.mark.skipif(
    not settings.recipes_db_path.exists(),
    reason="recipes.db has not been seeded yet — run `mealsight-seed` first",
)


async def test_recipe_corpus_section_coverage_stays_above_90_percent() -> None:
    recipe_db = get_recipe_db()
    pantry_db = get_pantry_db()
    try:
        synonym_map = await load_synonym_map(recipe_db)
        shelf_life_map = await load_shelf_life_map(pantry_db)

        rows = await recipe_db.fetch_all("SELECT ingredients FROM recipes")
        distinct: set[str] = set()
        for row in rows:
            for item in json.loads(row["ingredients"]):
                normalized = normalize_ingredient(item["name"])
                if normalized:
                    distinct.add(resolve_canonical(normalized, synonym_map))

        uncategorized = sorted(
            name for name in distinct if resolve_category(name, shelf_life_map) == "other"
        )
        categorized_count = len(distinct) - len(uncategorized)
        coverage_pct = (categorized_count / len(distinct) * 100) if distinct else 0.0

        assert coverage_pct >= MIN_SECTION_COVERAGE_PCT, (
            f"section coverage dropped to {coverage_pct:.1f}% "
            f"({categorized_count}/{len(distinct)} categorized) — "
            f"{len(uncategorized)} ingredient(s) fell through to 'other': {uncategorized}"
        )
    finally:
        await recipe_db.close()
        await pantry_db.close()
