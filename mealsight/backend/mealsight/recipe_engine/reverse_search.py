"""get_recipe_by_ingredients — reverse search: given a list of
ingredients (typically the pantry), find recipes that make good use of
THEM, rather than search_recipes' own direction (filter by constraints,
then optionally pre-rank by pantry overlap).

RELATIONSHIP TO search_recipes' OWN pantry-overlap PRE-RANKING
(_pantry_overlap_score in search.py) — read that function before this
one: it exists to answer "of the recipes matching these hard filters,
which uses more of what's on hand," scored as
    (this recipe's ingredients found in the pantry) / (this recipe's
    OWN total ingredient count).
That denominator is exactly wrong for THIS tool's own question — "given
this ingredient list, which recipe makes the best use of it" — because
it rewards a recipe using 3 of your 3 supplied ingredients out of a
15-ingredient recipe LESS than a recipe using those same 3 ingredients
out of a 4-ingredient recipe, even though from the caller's own point of
view (which ingredients did I actually get to use) the two are
identical. get_recipe_by_ingredients therefore flips the denominator to
the SUPPLIED list's own size:
    match_percentage = (recipe ingredients found in the supplied list)
                      / (the supplied list's own total length)
— so a recipe using 3 of 3 supplied ingredients scores 1.0 regardless of
how many OTHER ingredients that recipe also happens to need, correctly
ranking it above a recipe that only manages 1 of those same 3.

The canonicalization pipeline itself — normalize_ingredient +
resolve_canonical against the same synonym_map — is reused directly
from search.py's own _pantry_overlap_score rather than a third
implementation of "is this the same ingredient": only the formula's
denominator differs, not how two ingredient names are compared.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.recipe_engine.models import ReverseMatchedRecipe, ReverseSearchResults

DEFAULT_MINIMUM_MATCH_PERCENTAGE = 0.6


async def get_recipe_by_ingredients(
    db: Database,
    ingredients: Sequence[str],
    minimum_match_percentage: float = DEFAULT_MINIMUM_MATCH_PERCENTAGE,
    max_results: int = 20,
) -> ReverseSearchResults:
    """Ranks every recipe in recipes.db by what fraction of `ingredients`
    it actually uses (match_percentage — see this module's own docstring
    for exactly why that's the supplied list's own size, not the
    recipe's), keeping only those at or above minimum_match_percentage,
    highest match_percentage first (ties broken alphabetically by name,
    the same deterministic tiebreak search_recipes' own pantry-overlap
    ranking already uses).

    An empty `ingredients` list matches nothing (there's nothing to
    compute a percentage of) and returns an empty result immediately,
    without a database scan.

    Returns both the (possibly max_results-capped) ranked list and
    total_matched — how many recipes cleared minimum_match_percentage
    before the cap, the same "both the list and the real total" shape
    SearchResults already established.
    """
    if not ingredients:
        return ReverseSearchResults(results=[], total_matched=0)

    synonym_map = await load_synonym_map(db)
    supplied_canonical = {resolve_canonical(normalize_ingredient(name), synonym_map) for name in ingredients}

    rows = await db.fetch_all(
        "SELECT id, name, cuisine, meal_type, cook_time_minutes, ingredients FROM recipes"
    )

    scored: list[ReverseMatchedRecipe] = []
    for row in rows:
        recipe_ingredients: list[dict[str, Any]] = json.loads(row["ingredients"])
        recipe_canonical_by_name: dict[str, str] = {}
        for item in recipe_ingredients:
            name = item.get("name")
            if name:
                recipe_canonical_by_name[name] = resolve_canonical(
                    normalize_ingredient(name), synonym_map
                )

        recipe_canonical_set = set(recipe_canonical_by_name.values())
        matched_canonical = supplied_canonical & recipe_canonical_set
        if not matched_canonical:
            continue

        match_percentage = len(matched_canonical) / len(supplied_canonical)
        if match_percentage < minimum_match_percentage:
            continue

        matched_names = [
            name for name, canonical in recipe_canonical_by_name.items() if canonical in matched_canonical
        ]

        scored.append(
            ReverseMatchedRecipe(
                id=row["id"],
                name=row["name"],
                cuisine=row["cuisine"],
                meal_type=row["meal_type"],
                cook_time_minutes=row["cook_time_minutes"],
                match_percentage=match_percentage,
                matched_ingredient_names=matched_names,
                recipe_ingredient_count=len(recipe_ingredients),
            )
        )

    scored.sort(key=lambda r: (-r.match_percentage, r.name))
    return ReverseSearchResults(results=scored[:max_results], total_matched=len(scored))
