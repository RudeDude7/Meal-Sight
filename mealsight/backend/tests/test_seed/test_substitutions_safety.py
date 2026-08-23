"""Safety assertions on mealsight/seed/data/substitutions.json — Phase 2.2 filters on
dietary_notes, so a wrong tag here is a real, user-facing correctness bug
(e.g. recommending a substitute that isn't actually dairy-free to someone
who is lactose intolerant), not just a data-quality nitpick."""

from __future__ import annotations

from mealsight.seed.load_substitutions import load_substitution_entries

# Explicit dairy term list for this test, deliberately separate from
# recipe_parsing.DAIRY_TERMS: this one exists to catch a mistaken
# dairy_free tag on a substitute, so it also has to know about common
# non-dairy compounds (coconut cream, cashew cream, almond milk, ...)
# that legitimately contain a dairy-sounding word without being dairy.
_DAIRY_TERMS = ("milk", "butter", "cheese", "cream", "yogurt", "yoghurt", "ghee", "whey", "casein", "custard")
_NON_DAIRY_QUALIFIERS = (
    "coconut", "cashew", "almond", "oat", "soy", "rice milk", "vegan",
    "cocoa", "shea", "peanut", "hemp", "nutritional yeast",
)


def _mentions_real_dairy(text: str) -> bool:
    lowered = text.lower()
    if not any(term in lowered for term in _DAIRY_TERMS):
        return False
    return not any(qualifier in lowered for qualifier in _NON_DAIRY_QUALIFIERS)


def test_no_dairy_free_substitution_contains_a_dairy_derived_ingredient() -> None:
    entries = load_substitution_entries()
    violations = [
        entry
        for entry in entries
        if "dairy_free" in entry.get("dietary_notes", "") and _mentions_real_dairy(entry["substitute"])
    ]
    assert violations == [], f"dairy_free substitutes that mention real dairy: {violations}"


def test_ghee_is_never_suggested_as_a_butter_substitute() -> None:
    entries = load_substitution_entries()
    violations = [
        entry
        for entry in entries
        if entry["original_ingredient"] == "butter" and "ghee" in entry["substitute"].lower()
    ]
    assert violations == []


def test_honey_is_never_suggested_as_a_vegan_substitute() -> None:
    entries = load_substitution_entries()
    violations = [
        entry
        for entry in entries
        if "honey" in entry["substitute"].lower() and "vegan" in entry.get("dietary_notes", "")
    ]
    assert violations == []


def test_meets_minimum_entry_count() -> None:
    entries = load_substitution_entries()
    assert len(entries) >= 55


def test_every_entry_has_the_required_fields() -> None:
    required_fields = {"original_ingredient", "substitute", "ratio", "flavor_impact", "dietary_notes"}
    entries = load_substitution_entries()
    for entry in entries:
        missing = required_fields - entry.keys()
        assert not missing, f"{entry} is missing fields: {missing}"
        assert entry["flavor_impact"] in {"minimal", "noticeable", "significant"}
