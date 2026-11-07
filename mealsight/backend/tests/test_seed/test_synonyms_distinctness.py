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


# Unit- or form-qualified names found in the corpus audit (a quantity or portion word fused into the
# ingredient name). These ARE the same ingredient, so each must resolve to its base.
FUSED_UNIT_SYNONYMS = [
    ("garlic", "garlic clove"),
    ("basil", "basil leaf"),
    ("tarragon", "tarragon leaf"),
    ("fennel", "fennel bulb"),
    ("mozzarella", "mozzarella ball"),
    ("chicken stock", "chicken stock cube"),
    ("vegetable stock", "vegetable stock cube"),
]

# Names that look like the same shape but are genuinely different things, found in the same audit.
# They must NOT be collapsed onto the bare word.
DISTINCT_UNIT_NAMES = [
    ("bay", "bay leaf"),  # 'bay' alone is not an ingredient
    ("cinnamon", "cinnamon stick"),  # whole stick vs ground cinnamon
    ("lemon", "lemon juice"),
    ("lemon", "lemon zest"),
    ("orange", "orange zest"),
    ("gelatine", "gelatine leaf"),  # sheets vs powder
    ("chicken", "chicken stock cube"),  # a stock cube is stock, never chicken
]


def test_fused_unit_names_resolve_to_their_base_ingredient() -> None:
    pair_set = _as_pair_set(load_synonym_entries())
    for base, qualified in FUSED_UNIT_SYNONYMS:
        assert frozenset({base, qualified}) in pair_set, f"{qualified!r} should resolve to {base!r}"


def test_similar_looking_but_distinct_unit_names_are_not_collapsed() -> None:
    pair_set = _as_pair_set(load_synonym_entries())
    for a, b in DISTINCT_UNIT_NAMES:
        assert frozenset({a, b}) not in pair_set, f"{a!r} and {b!r} are different ingredients"
