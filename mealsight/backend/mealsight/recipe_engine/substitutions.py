"""find_substitutions — suggests substitutes for one ingredient, filtered
by why a substitute is needed.

Deterministic, no LLM calls. reason classifies why the caller wants a
substitute (surfaced in the result, and used purely for context); the
actual hard filtering is driven by dietary_restrictions, reusing the
exact same tag vocabulary (vegetarian, vegan, dairy_free, gluten_free,
nut_free) and the exact same eligibility check
(mealsight.matching.substitute_satisfies_dietary_restrictions) the
ingredient matcher uses for the same purpose — a dairy_free constraint
here excludes a dairy substitute the same way it would when matching a
recipe against a pantry, not a separately-invented rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from mealsight.db.connection import Database
from mealsight.matching.matcher import (
    FLAVOR_IMPACT_RANK,
    UNKNOWN_FLAVOR_IMPACT_RANK,
    substitute_satisfies_dietary_restrictions,
)
from mealsight.matching.normalize import normalize_ingredient
from mealsight.recipe_engine.models import SubstitutionReason, SubstitutionResult, SubstitutionSuggestion


async def find_substitutions(
    db: Database,
    ingredient_name: str,
    reason: SubstitutionReason,
    dietary_restrictions: Sequence[str] | None = None,
) -> SubstitutionResult:
    """Looks up substitutes for ingredient_name from the substitutions
    table, ranked by flavor_impact (minimal first). When reason is
    "allergic" or "dietary", dietary_restrictions must be supplied for
    the exclusion to actually happen — reason alone doesn't imply which
    restriction applies; it's on the caller to say (e.g. reason="dietary",
    dietary_restrictions=["dairy_free"])."""
    dietary_restrictions = dietary_restrictions or ()
    canonical = normalize_ingredient(ingredient_name)

    rows = await db.fetch_all(
        "SELECT substitute, ratio, flavor_impact, notes FROM substitutions WHERE original_ingredient = ?",
        (canonical,),
    )

    suggestions: list[SubstitutionSuggestion] = []
    excluded_count = 0
    for row in rows:
        if reason in ("allergic", "dietary") and not substitute_satisfies_dietary_restrictions(
            row["substitute"], dietary_restrictions
        ):
            excluded_count += 1
            continue
        suggestions.append(
            SubstitutionSuggestion(
                substitute=row["substitute"],
                ratio=row["ratio"] or "1:1",
                flavor_impact=row["flavor_impact"] or "significant",
                notes=row["notes"],
            )
        )

    suggestions.sort(key=lambda s: FLAVOR_IMPACT_RANK.get(s.flavor_impact, UNKNOWN_FLAVOR_IMPACT_RANK))

    return SubstitutionResult(
        ingredient=canonical,
        reason=reason,
        suggestions=suggestions,
        excluded_count=excluded_count,
    )
