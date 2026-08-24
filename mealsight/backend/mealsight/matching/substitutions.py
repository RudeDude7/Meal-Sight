"""Loads the substitutions table into an in-memory map keyed by
normalized original ingredient name, with the same load-once cache shape
as mealsight.matching.synonyms.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient


@dataclass(frozen=True)
class SubstitutionOption:
    substitute: str
    ratio: str
    flavor_impact: str


_substitution_cache: dict[str, list[SubstitutionOption]] | None = None


async def load_substitution_map(db: Database) -> dict[str, list[SubstitutionOption]]:
    """Loads every substitutions row into a dict of normalized
    original_ingredient -> its list of SubstitutionOption, caching the
    result in-process so repeated calls don't re-hit the database."""
    global _substitution_cache
    if _substitution_cache is not None:
        return _substitution_cache

    rows = await db.fetch_all(
        "SELECT original_ingredient, substitute, ratio, flavor_impact FROM substitutions"
    )
    mapping: dict[str, list[SubstitutionOption]] = defaultdict(list)
    for row in rows:
        key = normalize_ingredient(row["original_ingredient"])
        mapping[key].append(
            SubstitutionOption(
                substitute=row["substitute"],
                ratio=row["ratio"] or "1:1",
                flavor_impact=row["flavor_impact"] or "significant",
            )
        )

    _substitution_cache = dict(mapping)
    return _substitution_cache


def reset_substitution_cache() -> None:
    """Clears the in-memory cache. Exists for tests; application code has
    no reason to call this, since the substitutions table doesn't change
    at runtime."""
    global _substitution_cache
    _substitution_cache = None


def substitution_options_for(
    normalized_name: str, substitution_map: Mapping[str, Sequence[SubstitutionOption]]
) -> Sequence[SubstitutionOption]:
    return substitution_map.get(normalized_name, ())
