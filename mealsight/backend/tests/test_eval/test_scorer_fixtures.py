"""Known-answer fixtures for the eval's own scorers. Each case has a
correct answer worked out by hand, independent of the scorer; a scorer that
cannot pass them cannot measure the system. Dimension 1 (ingredient
recognition F1) and Dimension 2 (constraint satisfaction) are the only
dimensions implemented so far."""

from __future__ import annotations

from typing import Any

import pytest

from eval.cases import Case
from eval.dimension1 import aggregate_images
from eval.dimension2 import _check_case, summarize_cases
from eval.matching import ScoredImage, assign_matches, match_phrases
from eval.models import ImageResult
from mealsight.perception.models import UnifiedMealRequest


def _score(predicted: list[str], truth: list[str]) -> ScoredImage:
    matched_predicted, matched_truth = assign_matches(predicted, truth)
    return ScoredImage("fixture_photo", predicted, truth, matched_predicted, matched_truth)


# ----------------------------------------------------------------- Dimension 1


def test_d1_perfect_prediction_scores_exactly_one() -> None:
    scored = _score(["milk", "onion", "butter"], ["milk", "onion", "butter"])
    assert (scored.precision, scored.recall_raw, scored.f1_raw) == (1.0, 1.0, 1.0)


def test_d1_disjoint_prediction_scores_exactly_zero() -> None:
    scored = _score(["salmon", "rice"], ["milk", "onion", "butter"])
    assert (scored.precision, scored.recall_raw, scored.f1_raw) == (0.0, 0.0, 0.0)


def test_d1_empty_prediction_scores_zero_not_undefined() -> None:
    scored = _score([], ["milk"])
    assert scored.f1_raw == 0.0


@pytest.mark.parametrize(
    ("predicted", "truth"),
    [
        ("tomatoes", "tomato"),  # plural
        ("potatoes", "potato"),  # -oes plural
        ("blueberries", "blueberry"),  # -ies plural
        ("milk (carton labeled 2%)", "milk"),  # parenthetical qualifier
        ("carton of milk", "milk"),  # container word
        ("jar of tomato sauce", "tomato sauce"),  # container word, multi-word item
        ("half and half", "heavy cream"),  # curated synonym
        ("red bell pepper", "bell pepper"),  # compatible colour modifier
        ("sliced mushrooms", "mushroom"),  # compatible preparation modifier plus plural
        ("ground beef", "beef"),  # judgement call kept: ground beef is beef
    ],
)
def test_d1_near_misses_a_naive_matcher_gets_wrong_are_credited(predicted: str, truth: str) -> None:
    assert match_phrases(predicted, truth), f"{predicted!r} should match {truth!r}"
    assert _score([predicted], [truth]).f1_raw == 1.0


@pytest.mark.parametrize(
    ("predicted", "truth"),
    [
        ("sweet potato", "potato"),  # different food despite shared head noun
        ("cream cheese", "cheese"),  # different food, 'cream' is not a compatible modifier
        ("peanut butter", "butter"),  # different food
        ("goat cheese", "cheese"),  # dataset lists these separately
        ("green onion", "onion"),  # scallion is not a bulb onion
    ],
)
def test_d1_distinct_foods_that_share_a_word_are_not_merged(predicted: str, truth: str) -> None:
    assert not match_phrases(predicted, truth), f"{predicted!r} must not match {truth!r}"


def test_d1_duplicate_predictions_cannot_claim_one_truth_item_twice() -> None:
    scored = _score(["milk", "milk"], ["milk"])
    assert scored.recall_raw == 1.0
    assert scored.precision == 0.5  # the second 'milk' is a false positive


def test_d1_visibility_exclusion_changes_the_recall_denominator_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import eval.matching as matching

    monkeypatch.setattr(
        matching, "load_visibility_exclusions", lambda: frozenset({("fixture_photo", "butter")})
    )
    scored = _score(["milk"], ["milk", "butter"])
    assert scored.recall_raw == 0.5
    assert scored.recall_adjusted == 1.0
    assert scored.precision == 1.0


def _image(photo: str, f1: float, truth: list[str], error: str | None = None) -> ImageResult:
    return ImageResult(
        photo_id=photo,
        predicted_items=[] if f1 == 0.0 else ["x"],
        ground_truth_items=truth,
        precision=f1,
        recall_raw=f1,
        recall_adjusted=f1,
        f1_raw=f1,
        f1_adjusted=f1,
        error=error,
    )


def test_d1_aggregate_counts_a_photo_where_nothing_was_identified_as_zero() -> None:
    perfect = _image("a", 1.0, ["milk"])
    empty_but_scorable = _image("b", 0.0, ["milk"], error="I cannot identify any items with confidence")
    aggregate = aggregate_images([perfect, empty_but_scorable])
    assert aggregate["f1_adjusted"] == 0.5
    assert aggregate["images_scored"] == 2


def test_d1_aggregate_excludes_only_harness_failures_that_had_no_ground_truth() -> None:
    perfect = _image("a", 1.0, ["milk"])
    harness_failure = _image("b", 0.0, [], error="image file not found")
    aggregate = aggregate_images([perfect, harness_failure])
    assert aggregate["f1_adjusted"] == 1.0
    assert aggregate["images_scored"] == 1


# ----------------------------------------------------------------- Dimension 2


def _recipe(
    name: str = "Test Dish",
    tags: tuple[str, ...] = (),
    minutes: int | None = 20,
    ingredients: tuple[str, ...] = ("onion",),
    substitutable: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": "r1",
        "name": name,
        "dietary_tags": list(tags),
        "cook_time_minutes": minutes,
        "cuisine": "italian",
        "matched_items": [{"name": n} for n in ingredients],
        "missing_items": [],
        "partial_matches": [],
        "substitutable_items": [{"original": n, "substitute": "x"} for n in substitutable],
    }


def _state(
    recipe: dict[str, Any] | None,
    *,
    restrictions: list[str] | None = None,
    max_minutes: int | None = None,
    servings: int | None = None,
    avoid_ingredients: list[str] | None = None,
    avoid_dishes: list[str] | None = None,
    target_servings: int | None = None,
    max_is_default: bool = False,
) -> dict[str, Any]:
    unified = UnifiedMealRequest.model_construct(
        dietary_restrictions=restrictions or [],
        max_cook_time_minutes=max_minutes,
        max_cook_time_is_default=max_is_default,
        servings=servings,
        avoid_ingredients=avoid_ingredients or [],
        avoid_dishes=avoid_dishes or [],
    )
    top = {"available": True, "recipe_id": "r1"} if recipe else {"available": False}
    return {
        "unified_request": unified,
        "top_recommendation": top,
        "matched_recipes": [recipe] if recipe else [],
        "scaled_recipe": {"target_servings": target_servings} if target_servings is not None else {},
    }


def _case(**authored: Any) -> Case:
    return Case("fx", "fixture", "text", authored.pop("expect_refusal", False), **authored)


def test_d2_compliant_recommendation_passes_with_no_violations() -> None:
    case = _case(dietary=("vegan",), max_minutes=30, servings=2, avoid_ingredients=("mushroom",))
    state = _state(
        _recipe(tags=("vegan", "vegetarian"), minutes=25, ingredients=("onion", "lentil")),
        restrictions=["vegan"],
        max_minutes=30,
        servings=2,
        target_servings=2,
        avoid_ingredients=["mushroom"],
    )
    result = _check_case(case, state)  # type: ignore[arg-type]
    assert result.passed and not result.violations


def test_d2_dietary_violation_fails() -> None:
    case = _case(dietary=("vegan",))
    state = _state(_recipe(tags=("vegetarian",)), restrictions=["vegan"])
    result = _check_case(case, state)  # type: ignore[arg-type]
    assert not result.passed
    assert [v.constraint for v in result.violations] == ["dietary_restriction:vegan"]


def test_d2_dietary_violation_fails_even_when_extraction_dropped_the_restriction() -> None:
    # The pipeline extracted NO restriction, so a scorer that trusts the
    # pipeline's own unified_request would pass this. The case was authored vegan.
    case = _case(dietary=("vegan",))
    state = _state(_recipe(tags=()), restrictions=[])
    result = _check_case(case, state)  # type: ignore[arg-type]
    assert not result.passed, "scorer trusted the pipeline's own extraction, not the authored constraint"


def test_d2_hyphenated_restriction_matches_underscore_tag() -> None:
    case = _case(dietary=("gluten_free",))
    state = _state(_recipe(tags=("gluten_free",)), restrictions=["gluten-free"])
    assert _check_case(case, state).passed  # type: ignore[arg-type]


def test_d2_cook_time_over_the_limit_fails_and_exactly_at_the_limit_passes() -> None:
    case = _case(max_minutes=30)
    assert not _check_case(case, _state(_recipe(minutes=31), max_minutes=30)).passed  # type: ignore[arg-type]
    assert _check_case(case, _state(_recipe(minutes=30), max_minutes=30)).passed  # type: ignore[arg-type]


def test_d2_wrong_servings_fails() -> None:
    case = _case(servings=4)
    assert not _check_case(case, _state(_recipe(), servings=4, target_servings=2)).passed  # type: ignore[arg-type]
    assert _check_case(case, _state(_recipe(), servings=4, target_servings=4)).passed  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("avoid", "ingredients", "substitutable", "should_fail"),
    [
        ("mushrooms", ("mushroom", "onion"), (), True),  # plural vs singular
        ("peanuts", ("peanut butter",), (), True),  # avoided word inside a longer ingredient
        ("shellfish", ("king prawns", "olive oil"), (), True),  # allergen group, no shared word
        ("olives", ("black olives",), (), True),
        ("cilantro", ("fresh coriander",), (), True),  # US/UK synonym
        ("mushrooms", ("onion",), ("mushroom",), True),  # present only as a substitutable original
        ("mushrooms", ("onion", "garlic"), (), False),  # genuinely absent
        ("egg", ("eggplant",), (), False),  # substring but a different food
        ("nut", ("coconut milk",), (), False),  # substring but a different food
    ],
)
def test_d2_avoid_ingredient_detection(
    avoid: str, ingredients: tuple[str, ...], substitutable: tuple[str, ...], should_fail: bool
) -> None:
    case = _case(avoid_ingredients=(avoid,))
    state = _state(_recipe(ingredients=ingredients, substitutable=substitutable), avoid_ingredients=[avoid])
    assert _check_case(case, state).passed is (not should_fail)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("dish", "recipe_name", "should_fail"),
    [
        ("salad", "Greek Salad", True),
        ("soup", "Split Pea Soup", True),
        ("stir fry", "Beef Stir-Fry", True),  # hyphen vs space
        ("salad", "Salade Nicoise", False),  # a different word; no substring hit
        ("tea", "Steak and Chips", False),  # substring inside another word
        ("pie", "Spiced Lentil Stew", False),
    ],
)
def test_d2_avoid_dish_detection(dish: str, recipe_name: str, should_fail: bool) -> None:
    case = _case(avoid_dishes=(dish,))
    state = _state(_recipe(name=recipe_name), avoid_dishes=[dish])
    assert _check_case(case, state).passed is (not should_fail)  # type: ignore[arg-type]


def test_d2_honest_refusal_passes_when_the_case_is_unsatisfiable() -> None:
    case = _case(expect_refusal=True, dietary=("vegan", "gluten_free", "nut_free"))
    result = _check_case(case, _state(None))  # type: ignore[arg-type]
    assert result.passed and result.actual_refusal


def test_d2_refusal_of_a_satisfiable_case_fails() -> None:
    result = _check_case(_case(dietary=("vegan",)), _state(None))  # type: ignore[arg-type]
    assert not result.passed


def test_d2_recommending_something_for_an_unsatisfiable_case_fails() -> None:
    case = _case(expect_refusal=True, dietary=("vegan", "gluten_free", "nut_free"))
    state = _state(_recipe(tags=("vegan", "gluten_free", "nut_free")))  # even a fully tagged recipe
    result = _check_case(case, state)  # type: ignore[arg-type]
    assert not result.passed
    assert "expected_refusal" in [v.constraint for v in result.violations]


def test_d2_dimension_does_not_pass_when_a_satisfiable_case_was_wrongly_refused() -> None:
    ok = _check_case(_case(dietary=("vegan",)), _state(_recipe(tags=("vegan",)), restrictions=["vegan"]))  # type: ignore[arg-type]
    wrongly_refused = _check_case(_case(dietary=("vegan",)), _state(None))  # type: ignore[arg-type]
    score, passed = summarize_cases([ok, wrongly_refused])
    assert score == 0.5
    assert passed is False, "dimension reports PASS although a case failed and the threshold is 1.0"


def test_d2_dimension_passes_only_when_every_case_passes() -> None:
    ok = _check_case(_case(dietary=("vegan",)), _state(_recipe(tags=("vegan",)), restrictions=["vegan"]))  # type: ignore[arg-type]
    refused = _check_case(_case(expect_refusal=True), _state(None))  # type: ignore[arg-type]
    assert summarize_cases([ok, refused]) == (1.0, True)
    assert summarize_cases([]) == (0.0, False)


def test_d2_profile_default_cook_time_is_not_enforced_as_a_user_limit() -> None:
    # The user stated no time; the 30 is the profile default. A 60-minute
    # recipe is a correct answer and must not be failed for exceeding it.
    case = _case(dietary=("vegan",))
    state = _state(
        _recipe(tags=("vegan",), minutes=60), restrictions=["vegan"], max_minutes=30, max_is_default=True
    )
    result = _check_case(case, state)  # type: ignore[arg-type]
    assert result.passed and not result.violations


def test_d2_stated_cook_time_is_still_enforced_when_it_matches_the_default_value() -> None:
    case = _case(max_minutes=30)
    state = _state(_recipe(minutes=60), max_minutes=30, max_is_default=False)
    assert not _check_case(case, state).passed  # type: ignore[arg-type]


def test_d2_soft_cuisine_is_scored_separately_from_the_hard_pass() -> None:
    # A non-matching cuisine must not fail the case; it scores 0.0 on the soft axis only.
    case = _case(dietary=("vegetarian",), cuisine_soft="italian")
    british = {**_recipe(tags=("vegetarian",)), "cuisine": "British"}
    miss = _check_case(case, _state(british, restrictions=["vegetarian"]))  # type: ignore[arg-type]
    assert miss.passed and miss.soft_score == 0.0
    italian = {**_recipe(tags=("vegetarian",)), "cuisine": "Italian"}
    hit = _check_case(case, _state(italian, restrictions=["vegetarian"]))  # type: ignore[arg-type]
    assert hit.passed and hit.soft_score == 1.0


def test_d2_soft_miss_does_not_hide_a_hard_violation() -> None:
    case = _case(dietary=("vegetarian",), cuisine_soft="italian")
    meat = {**_recipe(tags=()), "cuisine": "Italian"}
    result = _check_case(case, _state(meat, restrictions=["vegetarian"]))  # type: ignore[arg-type]
    assert not result.passed and result.soft_score == 1.0


def test_d2_ingredient_enforced_restriction_violation_fails() -> None:
    # peanut-free has no corpus tag; the scorer must read the ingredient list itself.
    case = _case(dietary=("peanut_free",))
    bad = _check_case(
        case, _state(_recipe(ingredients=("peanut butter", "bread")), restrictions=["peanut-free"])
    )  # type: ignore[arg-type]
    assert not bad.passed
    assert [v.constraint for v in bad.violations] == ["dietary_restriction:peanut_free"]
    assert _check_case(case, _state(_recipe(ingredients=("bread",)), restrictions=["peanut-free"])).passed  # type: ignore[arg-type]


def test_d2_pescatarian_rejects_meat_stock_and_allows_fish() -> None:
    case = _case(dietary=("pescatarian",))
    assert not _check_case(case, _state(_recipe(ingredients=("chicken stock cube",)))).passed  # type: ignore[arg-type]
    assert _check_case(case, _state(_recipe(ingredients=("salmon", "prawns")))).passed  # type: ignore[arg-type]


def test_d2_halal_and_kosher_checks() -> None:
    halal = _case(dietary=("halal",))
    state = _state(_recipe(ingredients=("dry white wine",)))
    state["top_recommendation"] = {
        "available": True,
        "recipe_id": "r1",
        "note": "certification cannot be verified",
    }
    assert not _check_case(halal, state).passed  # type: ignore[arg-type]
    vinegar = _state(_recipe(ingredients=("red wine vinegar",)))
    vinegar["top_recommendation"] = state["top_recommendation"]
    assert _check_case(halal, vinegar).passed  # type: ignore[arg-type]
    kosher = _case(dietary=("kosher",))
    mixed = _state(_recipe(ingredients=("chicken", "butter")))
    mixed["top_recommendation"] = state["top_recommendation"]
    assert not _check_case(kosher, mixed).passed  # type: ignore[arg-type]


def test_d2_partial_restriction_must_state_what_it_does_not_cover() -> None:
    case = _case(dietary=("halal",))
    silent = _check_case(case, _state(_recipe(ingredients=("rice",))))  # type: ignore[arg-type]
    assert not silent.passed
    assert [v.constraint for v in silent.violations] == ["disclosure:halal"]


def test_d2_unenforced_restriction_must_be_disclosed_not_silently_dropped() -> None:
    case = _case(dietary=("low_sodium",))
    silent = _check_case(case, _state(_recipe()))  # type: ignore[arg-type]
    assert not silent.passed and silent.violations[0].constraint == "disclosure:low_sodium"
    disclosed = _state(_recipe())
    disclosed["top_recommendation"] = {
        "available": True,
        "recipe_id": "r1",
        "reasoning": "NOT ENFORCED: low-sodium. Sodium cannot be estimated reliably.",
    }
    assert _check_case(case, disclosed).passed  # type: ignore[arg-type]


def test_d4_an_expiring_staple_replaces_the_never_expiring_staple_in_a_pantry() -> None:
    """Regression for a case-construction bug: butter is a staple, and asking for it to expire left it
    fresh, so the case silently tested nothing. The harness caught it as a case defect."""
    from eval.cases4 import FRESHNESS_CASES

    case = next(c for c in FRESHNESS_CASES if c.case_id == "d4_13")
    butter = [i for i in case.pantry if i.name == "butter"]
    assert len(butter) == 1 and butter[0].days_remaining == 1
