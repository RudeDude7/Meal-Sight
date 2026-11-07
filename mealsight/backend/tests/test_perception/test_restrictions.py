import pytest

from mealsight.perception.restrictions import detect_dietary_restrictions


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I need something vegan, gluten-free, and nut-free.", {"vegan", "gluten-free", "nut-free"}),
        ("I need a nut-free meal, someone here has a nut allergy.", {"nut-free"}),
        ("I need a vegan recipe with no nuts, nut allergy in the house.", {"vegan", "nut-free"}),
        ("Vegetarian and dairy-free please, no dairy at all.", {"vegetarian", "dairy-free"}),
        ("I'm allergic to nuts.", {"nut-free"}),
        ("something with no gluten", {"gluten-free"}),
        ("Give me a recipe.", set()),
        ("I have coconut and nutmeg", set()),
    ],
)
def test_detects_stated_restrictions(text: str, expected: set[str]) -> None:
    assert set(detect_dietary_restrictions(text)) == expected


def test_negated_restriction_is_not_added() -> None:
    assert detect_dietary_restrictions("I'm not vegetarian, surprise me") == []
    assert detect_dietary_restrictions("non-vegan is fine") == []


def test_stands_down_on_self_correction() -> None:
    assert detect_dietary_restrictions("no dairy, oh wait, cheese is fine, just no milk") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cooking for four, nothing with peanuts, my daughter's allergic.", {"peanut-free"}),
        ("I have a shellfish allergy, avoid shellfish entirely.", {"shellfish-free"}),
        ("soy-free and egg-free please", {"soy-free", "egg-free"}),
        ("I'm pescatarian", {"pescatarian"}),
        ("something halal", {"halal"}),
        ("a kosher dinner", {"kosher"}),
        ("keto and low-carb", {"keto", "low-carb"}),
        ("low sodium please", {"low-sodium"}),
        ("I have no eggs left", set()),  # a pantry statement, not a restriction
    ],
)
def test_detects_the_restrictions_that_have_no_corpus_tag(text: str, expected: set[str]) -> None:
    assert set(detect_dietary_restrictions(text)) == expected
