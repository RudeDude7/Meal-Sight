"""Tests for mealsight.matching.synonyms.resolve_canonical."""

from __future__ import annotations

from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import resolve_canonical

_SYNONYM_MAP = {
    "capsicum": "bell pepper",
    "scallion": "green onion",
}


def test_synonym_resolves_to_canonical_name() -> None:
    normalized = normalize_ingredient("Capsicum")
    assert resolve_canonical(normalized, _SYNONYM_MAP) == "bell pepper"


def test_bell_pepper_and_capsicum_unify_to_the_same_canonical_name() -> None:
    bell_pepper = resolve_canonical(normalize_ingredient("bell pepper"), _SYNONYM_MAP)
    capsicum = resolve_canonical(normalize_ingredient("capsicum"), _SYNONYM_MAP)
    assert bell_pepper == capsicum == "bell pepper"


def test_potato_and_sweet_potato_do_not_unify() -> None:
    potato = resolve_canonical(normalize_ingredient("potato"), _SYNONYM_MAP)
    sweet_potato = resolve_canonical(normalize_ingredient("sweet potato"), _SYNONYM_MAP)
    assert potato != sweet_potato


def test_unknown_name_resolves_to_itself() -> None:
    normalized = normalize_ingredient("quinoa")
    assert resolve_canonical(normalized, _SYNONYM_MAP) == "quinoa"


def test_resolution_is_exact_not_substring() -> None:
    # A synonym map entry for "chicken" must not cause "chicken stock" to
    # resolve as if it partially matched "chicken".
    synonym_map = {"chicken": "poultry"}
    normalized = normalize_ingredient("Chicken Stock")
    assert resolve_canonical(normalized, synonym_map) == "chicken stock"
