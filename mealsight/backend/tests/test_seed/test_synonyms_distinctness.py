"""Assertions that mealsight/seed/data/ingredient_synonyms.json never collapses two
genuinely distinct ingredients into one canonical name."""

from __future__ import annotations

from mealsight.seed.load_synonyms import load_synonym_entries

# Pairs that share words or category but must never be linked as synonyms.
# Order within each tuple doesn't matter; both directions are checked.
DISTINCT_PAIRS = [
    ("potato", "sweet potato"),
    ("cream", "cream cheese"),
    ("cream", "sour cream"),
    ("milk", "coconut milk"),
    ("butter", "peanut butter"),
    ("butter", "cocoa butter"),
    ("onion", "green onion"),
    ("chicken", "chicken stock"),
    ("sugar", "brown sugar"),
]


def _as_pair_set(entries: list[dict[str, str]]) -> set[frozenset[str]]:
    return {frozenset({entry["canonical_name"], entry["synonym"]}) for entry in entries}


def test_distinct_ingredient_pairs_are_never_linked_as_synonyms() -> None:
    entries = load_synonym_entries()
    pair_set = _as_pair_set(entries)

    for a, b in DISTINCT_PAIRS:
        assert frozenset({a, b}) not in pair_set, f"{a!r} and {b!r} must not be synonyms of each other"


def test_meets_minimum_entry_count() -> None:
    entries = load_synonym_entries()
    assert len(entries) >= 80


def test_no_name_is_both_a_canonical_and_a_synonym() -> None:
    # A name playing both roles would make the "canonical" name ambiguous
    # — is it the standard form, or itself just another alias?
    entries = load_synonym_entries()
    canonicals = {entry["canonical_name"] for entry in entries}
    synonyms = {entry["synonym"] for entry in entries}
    overlap = canonicals & synonyms
    assert overlap == set(), f"names used as both canonical and synonym: {overlap}"


def test_no_duplicate_pairs() -> None:
    entries = load_synonym_entries()
    pairs = [(entry["canonical_name"], entry["synonym"]) for entry in entries]
    assert len(pairs) == len(set(pairs))
