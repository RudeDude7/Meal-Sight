"""Resolves a normalized ingredient name to its canonical form via the
ingredient_synonyms table, with an in-memory cache loaded once per
process — the same singleton-cache shape mealsight.db.connection uses for
its Database instances.

Lookup is exact-match on the already-normalized form, never substring:
"chicken stock" must not resolve just because it contains "chicken".
"""

from __future__ import annotations

from collections.abc import Mapping

from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient

_synonym_cache: dict[str, str] | None = None


async def load_synonym_map(db: Database) -> dict[str, str]:
    """Loads every (canonical_name, synonym) pair from ingredient_synonyms
    into a dict of normalized synonym -> normalized canonical name, caching
    the result in-process so repeated calls don't re-hit the database."""
    global _synonym_cache
    if _synonym_cache is not None:
        return _synonym_cache

    rows = await db.fetch_all("SELECT canonical_name, synonym FROM ingredient_synonyms")
    mapping: dict[str, str] = {}
    for row in rows:
        synonym_key = normalize_ingredient(row["synonym"])
        canonical_value = normalize_ingredient(row["canonical_name"])
        mapping[synonym_key] = canonical_value

    _synonym_cache = mapping
    return _synonym_cache


def reset_synonym_cache() -> None:
    """Clears the in-memory cache, so the next load_synonym_map call reads
    fresh from the database. Exists for tests — application code has no
    reason to call this, since the synonym table doesn't change at
    runtime."""
    global _synonym_cache
    _synonym_cache = None


def resolve_canonical(normalized_name: str, synonym_map: Mapping[str, str]) -> str:
    """Resolves an already-normalized ingredient name to its canonical
    form, if the synonym table has one — an exact-match dict lookup, never
    a substring search. Returns the input unchanged if it isn't a known
    synonym of anything (it may already be canonical, or simply unknown)."""
    return synonym_map.get(normalized_name, normalized_name)
