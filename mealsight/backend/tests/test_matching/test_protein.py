"""The shared protein lexicon, and everything that uses it."""

from __future__ import annotations

from typing import Any

import pytest

from mealsight.agent.nodes.match_rank import PROTEIN_PREFERENCE_WEIGHT, match_rank
from mealsight.agent.reasoning_facts import protein_met, protein_shortfall_note
from mealsight.matching.protein import PROTEIN_GROUPS, names_include_protein, protein_members
from tests.test_agent.test_nodes import RecipeAwareMCP, _fake_runtime, _match_data, _recipe, _unified


@pytest.mark.parametrize(
    ("preference", "names", "expected"),
    [
        ("seafood or fish", ["Salmon fillet", "lemon"], True),
        ("seafood or fish", ["king prawns"], True),
        ("seafood", ["squid"], True),
        ("fish", ["tuna"], True),
        ("fish", ["fish sauce"], False),  # flavouring, not the protein
        ("chicken", ["chicken stock cube"], False),
        ("chicken", ["Chicken thighs"], True),
        ("poultry", ["turkey breast"], True),
        ("poultry", ["beef"], False),
        ("meat", ["lamb mince"], True),
        ("meat", ["chicken breast"], True),  # "meat" includes poultry
        ("red meat", ["chicken breast"], False),
        ("red meat", ["beef brisket"], True),
        ("shrimp", ["raw king prawns"], True),  # one animal, two names
        ("chicken and beef", ["beef brisket"], True),
        ("egg", ["eggplant"], False),  # whole words only
        ("fish", ["starfish crackers"], False),
        ("seafood or fish", ["chicken", "onion"], False),
    ],
)
def test_protein_matching(preference: str, names: list[str], expected: bool) -> None:
    assert names_include_protein(names, preference) is expected


def test_seafood_contains_every_fish_and_shellfish_member() -> None:
    for member in ("salmon", "tuna", "cod", "prawn", "shrimp", "crab"):
        assert member in protein_members("seafood")
    assert {"fish", "shellfish", "seafood", "poultry", "meat", "red meat"} <= set(PROTEIN_GROUPS)


def _recipe_with(names: list[str]) -> dict[str, Any]:
    return {"matched_items": [{"name": n} for n in names], "missing_items": []}


def test_protein_met_reports_a_salmon_dish_as_seafood() -> None:
    salmon = _recipe_with(["salmon fillet", "lemon"])
    assert protein_met("seafood or fish", salmon) is True
    assert protein_met("fish", salmon) is True
    assert protein_met("chicken", salmon) is False


def test_protein_met_is_unchanged_for_a_general_high_protein_ask() -> None:
    assert protein_met("high-protein", _recipe_with(["salmon"])) is None


# ------------------------------------------------------------------ ranking


async def _scores(preference: str | None, data: dict[str, dict[str, Any]]) -> dict[str, float]:
    mcp = RecipeAwareMCP(match_ingredients=data)
    state: Any = {
        "recipe_candidates": [_recipe(r) for r in data],
        "pantry_items": [{"name": "onion"}],
        "unified_request": _unified(protein_preference=preference),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))
    return {r["recipe_id"]: r["composite_score"] for r in result["matched_recipes"]}


def _cookable(score: float, name: str) -> dict[str, Any]:
    return _match_data(score, matched_items=[{"name": name}], can_cook=True)


async def test_protein_weight_equals_the_cuisine_weight() -> None:
    from mealsight.agent.nodes.match_rank import CUISINE_PREFERENCE_WEIGHT

    assert PROTEIN_PREFERENCE_WEIGHT == CUISINE_PREFERENCE_WEIGHT == 0.15


async def test_cookable_recipe_with_the_asked_protein_gets_exactly_the_lift() -> None:
    data = {"chick": _cookable(0.5, "chicken"), "veg": _cookable(0.5, "carrot")}
    without = await _scores(None, data)
    with_pref = await _scores("chicken", data)
    assert with_pref["chick"] == pytest.approx(without["chick"] + PROTEIN_PREFERENCE_WEIGHT)
    assert with_pref["veg"] == pytest.approx(without["veg"])


async def test_preference_changes_the_ranking_between_two_requests_over_the_same_pantry() -> None:
    data = {"chick": _cookable(0.45, "chicken"), "salmon": _cookable(0.45, "salmon fillet")}
    chicken_request = await _scores("chicken", data)
    seafood_request = await _scores("seafood or fish", data)
    assert chicken_request["chick"] > chicken_request["salmon"]
    assert seafood_request["salmon"] > seafood_request["chick"]


async def test_an_uncookable_recipe_with_the_protein_gets_no_lift() -> None:
    uncookable = _match_data(0.5, matched_items=[{"name": "salmon"}], can_cook=False)
    with_pref = await _scores("seafood or fish", {"fish": uncookable})
    without = await _scores(None, {"fish": uncookable})
    assert with_pref["fish"] == pytest.approx(without["fish"])


async def test_an_uncookable_seafood_recipe_missing_its_fish_cannot_outrank_a_cookable_chicken_one() -> None:
    # The real shape: the fish itself is the critical missing ingredient.
    seafood = _match_data(0.5, critical_missing=["salmon"], can_cook=False)
    seafood["missing_items"] = [{"name": "salmon fillet"}]
    chicken = _cookable(0.4, "chicken")
    scores = await _scores("seafood or fish", {"fish": seafood, "chick": chicken})
    assert scores["chick"] > scores["fish"]


async def test_the_preference_is_a_preference_not_a_filter() -> None:
    # A far better-stocked cookable recipe still beats a barely-cookable one with the protein.
    data = {"strong": _cookable(0.9, "carrot"), "weak": _cookable(0.3, "chicken")}
    scores = await _scores("chicken", data)
    assert scores["strong"] > scores["weak"]


async def test_a_general_high_protein_ask_does_not_lift_anything_at_ranking_time() -> None:
    data = {"a": _cookable(0.5, "chicken")}
    assert await _scores("high-protein", data) == await _scores(None, data)


# ------------------------------------------------------------------ honesty


def test_shortfall_note_says_the_pantry_has_none_when_that_is_why() -> None:
    candidates = [{"can_cook": True, "name": "Chicken Handi"}]
    note = protein_shortfall_note("seafood or fish", candidates, ["chicken"])
    assert "pantry has no seafood or fish" in note
    assert "does not meet that preference" in note


def test_shortfall_note_distinguishes_have_it_but_cannot_cook() -> None:
    uncookable = {"can_cook": False, "name": "Fish Pie", **_recipe_with(["salmon"])}
    note = protein_shortfall_note("fish", [uncookable], ["salmon fillet"])
    assert "can be cooked" in note and "pantry has no" not in note


def test_shortfall_note_names_a_cookable_alternative_that_lost() -> None:
    winner_elsewhere = {"can_cook": True, "name": "Grilled Salmon", **_recipe_with(["salmon"])}
    assert "Grilled Salmon" in protein_shortfall_note("fish", [winner_elsewhere], ["salmon"])
