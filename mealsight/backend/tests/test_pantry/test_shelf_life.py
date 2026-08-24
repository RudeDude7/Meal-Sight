"""Tests for mealsight.pantry.shelf_life.resolve_shelf_life."""

from __future__ import annotations

from mealsight.pantry.shelf_life import CATEGORY_DEFAULTS, ShelfLifeEntry, resolve_shelf_life

_MAP = {
    "chicken": ShelfLifeEntry(
        category="protein", shelf_days_refrigerated=2, shelf_days_frozen=270, shelf_days_pantry=None
    ),
    "rice": ShelfLifeEntry(
        category="grain", shelf_days_refrigerated=None, shelf_days_frozen=None, shelf_days_pantry=730
    ),
}


def test_known_item_uses_its_exact_row() -> None:
    assert resolve_shelf_life("chicken", "protein", _MAP) == 2


def test_pantry_only_item_falls_back_to_its_own_pantry_value() -> None:
    assert resolve_shelf_life("rice", "grain", _MAP) == 730


def test_unknown_item_falls_back_to_category_default() -> None:
    result = resolve_shelf_life("some totally unheard of vegetable", "vegetable", _MAP)
    assert result == CATEGORY_DEFAULTS["vegetable"].shelf_days_refrigerated


def test_unknown_item_and_unknown_category_still_returns_a_sane_number() -> None:
    result = resolve_shelf_life("mystery item", "not_a_real_category", _MAP)
    assert isinstance(result, int)
    assert result > 0


def test_category_lookup_is_case_insensitive() -> None:
    assert resolve_shelf_life("unknown thing", "PROTEIN", _MAP) == resolve_shelf_life(
        "unknown thing", "protein", _MAP
    )
