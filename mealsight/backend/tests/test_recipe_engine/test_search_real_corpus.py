"""Guards agent/nodes/search_recipes.py's own MEAL_TYPE_TO_CORPUS_TYPES
mapping against the real seeded recipe corpus — the actual defect this
mapping exists to fix: a time-of-day meal_type that maps to a corpus
value (or set of values) with zero real rows behind it is exactly as
useless as the exact-match bug it replaces, just failing more quietly.

Deliberately checks the real, already-seeded recipes.db, the same
reasoning test_pantry/test_section_coverage.py already uses for exactly
this kind of "does this mapping still hold against real data" check.
Skips cleanly on a machine where recipes.db hasn't been seeded yet.
"""

from __future__ import annotations

import pytest

from mealsight.agent.nodes.search_recipes import MEAL_TYPE_TO_CORPUS_TYPES
from mealsight.config.settings import settings
from mealsight.db import get_recipe_db
from mealsight.recipe_engine.search import search_recipes

pytestmark = pytest.mark.skipif(
    not settings.recipes_db_path.exists(),
    reason="recipes.db has not been seeded yet — run `mealsight-seed` first",
)


async def test_meal_type_mapping_produces_non_empty_results_for_every_time_of_day() -> None:
    """Every one of the four inferred time-of-day values must map to at
    least one recipe in the real corpus — the literal bar defect 1 was
    found for: a mapping that quietly matches nothing is the same bug
    wearing a mapping table instead of a single wrong string."""
    recipe_db = get_recipe_db()
    try:
        empty: list[str] = []
        for meal_type, corpus_types in MEAL_TYPE_TO_CORPUS_TYPES.items():
            result = await search_recipes(
                recipe_db, dietary_filters=[], meal_type=list(corpus_types), max_results=1
            )
            if result.total_matched == 0:
                empty.append(meal_type)
        assert not empty, f"these time-of-day mappings match zero real recipes: {empty}"
    finally:
        await recipe_db.close()


async def test_breakfast_mapping_is_the_real_narrow_corpus_category_not_diluted_with_main() -> None:
    """The hard case, checked directly rather than assumed: breakfast
    stays scoped to the corpus's own real "breakfast" category alone,
    not widened with "main" (168 of 250 recipes) just to inflate the
    count — diluting it that far would erase the exact distinction this
    mapping exists to create."""
    assert MEAL_TYPE_TO_CORPUS_TYPES["breakfast"] == ("breakfast",)

    recipe_db = get_recipe_db()
    try:
        result = await search_recipes(recipe_db, dietary_filters=[], meal_type="breakfast", max_results=50)
        assert result.total_matched > 0, "the real corpus must have at least one breakfast-tagged recipe"
    finally:
        await recipe_db.close()
