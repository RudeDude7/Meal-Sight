import pytest

from mealsight.matching.diet import (
    INGREDIENT_ENFORCED,
    PARTIAL,
    TAG_BACKED,
    UNENFORCED,
    describe_enforcement,
    ingredient_violations,
    split_restrictions,
    violated_ingredient_restrictions,
)
from mealsight.perception.dietary import DIETARY_RESTRICTION_VOCABULARY


def test_every_vocabulary_restriction_is_in_exactly_one_group() -> None:
    groups = [
        TAG_BACKED,
        frozenset(INGREDIENT_ENFORCED),
        frozenset(UNENFORCED),
    ]
    assert frozenset().union(*groups) == DIETARY_RESTRICTION_VOCABULARY
    assert sum(len(g) for g in groups) == len(DIETARY_RESTRICTION_VOCABULARY)


def test_the_five_tag_backed_restrictions_are_exactly_the_corpus_tags() -> None:
    assert {"vegetarian", "vegan", "dairy-free", "gluten-free", "nut-free"} == TAG_BACKED


def test_only_tag_backed_restrictions_become_search_filters() -> None:
    split = split_restrictions(["vegan", "gluten-free", "peanut-free", "halal", "keto", "paleo"])
    assert split.tag_filters == ["vegan", "gluten_free"]
    assert split.ingredient == ["peanut-free", "halal"]
    assert split.unenforced == ["keto", "paleo"]


def test_an_unclassified_restriction_is_disclosed_never_a_tag_filter() -> None:
    split = split_restrictions(["carnivore"])
    assert split.tag_filters == [] and split.unenforced == ["carnivore"]


@pytest.mark.parametrize(
    ("restriction", "ingredients", "violates"),
    [
        ("peanut-free", ["Peanut Butter", "onion"], True),
        ("peanut-free", ["almond", "onion"], False),  # tree nut is not a peanut
        ("shellfish-free", ["King Prawns"], True),
        ("shellfish-free", ["salmon"], False),
        ("soy-free", ["soy sauce"], True),
        ("soy-free", ["Tofu"], True),
        ("egg-free", ["Eggs"], True),
        ("egg-free", ["eggplant", "Mayonnaise"], True),  # mayonnaise contains egg
        ("egg-free", ["eggplant"], False),
        ("pescatarian", ["chicken stock", "carrot"], True),  # stock is made from the meat
        ("pescatarian", ["salmon", "prawns", "rice"], False),  # fish and shellfish are allowed
        ("pescatarian", ["beef mince"], True),
        ("halal", ["bacon"], True),
        ("halal", ["white wine"], True),
        ("halal", ["red wine vinegar"], False),  # vinegar is not alcohol
        ("kosher", ["pork belly"], True),
        ("kosher", ["prawns"], True),
        ("kosher", ["chicken", "butter"], True),  # meat with dairy
        ("kosher", ["beef", "onion"], False),
        ("kosher", ["cheese", "pasta"], False),
    ],
)
def test_ingredient_enforcement(restriction: str, ingredients: list[str], violates: bool) -> None:
    assert bool(ingredient_violations(restriction, ingredients)) is violates


def test_violation_reason_names_the_offending_ingredient() -> None:
    assert violated_ingredient_restrictions(["peanut-free"], ["Peanut Butter"]) == [
        "peanut-free: peanut (Peanut Butter)"
    ]


def test_partial_checks_say_what_they_do_not_cover() -> None:
    assert {"halal", "kosher"} == PARTIAL
    assert "certification" in describe_enforcement("halal")
    assert "certification" in describe_enforcement("kosher")


def test_unenforced_restrictions_are_declared_as_such() -> None:
    for restriction in ("low-sodium", "low-fat", "low-carb", "keto", "paleo"):
        assert describe_enforcement(restriction).startswith(f"{restriction}: NOT enforced")
