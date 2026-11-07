import pytest

from mealsight.matching.cuisine import corpus_labels_for, cuisine_key, cuisines_match, known_labels

# The distinct cuisine labels in the seeded corpus (24), from
# `SELECT cuisine, COUNT(*) FROM recipes GROUP BY cuisine`.
CORPUS_LABELS = [
    "British",
    "United States",
    "France",
    "Italian",
    "Canadian",
    "Chinese",
    "India",
    "Greek",
    "Jamaican",
    "Polish",
    "Tunisian",
    "Egyptian",
    "Japanese",
    "Mexican",
    "Moroccan",
    "Irish",
    "Netherlands",
    "Spanish",
    "Thai",
    "Kenyan",
    "Turkish",
    "Vietnamese",
    "Malaysian",
    "Russian",
]


@pytest.mark.parametrize(
    ("asked", "label"),
    [
        ("Indian", "India"),
        ("india", "India"),
        ("INDIAN", "India"),
        ("French", "France"),
        ("france", "France"),
        ("American", "United States"),
        ("USA", "United States"),
        ("united states", "United States"),
        ("Dutch", "Netherlands"),
        ("Netherlands", "Netherlands"),
        ("Italian", "Italian"),
        ("italy", "Italian"),
        ("English", "British"),
        ("UK", "British"),
        ("Greece", "Greek"),
        ("  mexican  ", "Mexican"),
    ],
)
def test_either_form_in_either_case_matches_the_corpus_label(asked: str, label: str) -> None:
    assert cuisines_match(asked, label)
    assert cuisines_match(label, asked), "must work in both directions"


def test_different_cuisines_do_not_match() -> None:
    assert not cuisines_match("Indian", "Italian")
    assert not cuisines_match("French", "British")
    assert not cuisines_match(None, "India")
    assert not cuisines_match("Indian", None)


def test_every_corpus_label_is_reachable_by_itself_and_by_its_country_or_demonym() -> None:
    assert set(CORPUS_LABELS) == set(known_labels()), "a corpus label has no family, or a family has no label"
    for label in CORPUS_LABELS:
        assert corpus_labels_for(label, CORPUS_LABELS) == [label]
        assert corpus_labels_for(label.lower(), CORPUS_LABELS) == [label]


def test_every_label_has_an_alternate_name_that_resolves_to_it() -> None:
    alternates = {
        "India": "Indian",
        "France": "French",
        "Netherlands": "Dutch",
        "United States": "American",
        "Italian": "Italy",
        "Greek": "Greece",
        "Thai": "Thailand",
        "Turkish": "Turkey",
        "Mexican": "Mexico",
        "Chinese": "China",
        "Japanese": "Japan",
        "Polish": "Poland",
        "Spanish": "Spain",
        "Irish": "Ireland",
        "Canadian": "Canada",
        "Jamaican": "Jamaica",
        "Egyptian": "Egypt",
        "Tunisian": "Tunisia",
        "Moroccan": "Morocco",
        "Kenyan": "Kenya",
        "Vietnamese": "Vietnam",
        "Malaysian": "Malaysia",
        "Russian": "Russia",
        "British": "Britain",
    }
    assert set(alternates) == set(CORPUS_LABELS)
    for label, alt in alternates.items():
        assert corpus_labels_for(alt, CORPUS_LABELS) == [label], (label, alt)


def test_unknown_label_still_matches_itself() -> None:
    assert cuisine_key("Ethiopian") == "ethiopian"
    assert cuisines_match("ethiopian", "Ethiopian")


def test_canonical_label_and_lookup_resolve_every_spelling_together() -> None:
    from mealsight.matching.cuisine import (
        canonical_cuisine_label,
        collapse_cuisine_scores,
        lookup_cuisine_score,
    )

    for spelling in ("italian", "Italian", "ITALIAN", "Italy"):
        assert canonical_cuisine_label(spelling) == "Italian"
    assert canonical_cuisine_label("Indian") == "India" and canonical_cuisine_label("french") == "France"
    assert canonical_cuisine_label("ethiopian") == "Ethiopian"  # unknown: capitalized, still stable
    # The production bug: profile keys keep their logged capitalization, recipes use the corpus label.
    assert lookup_cuisine_score({"Italian": 0.885}, "Italian") == 0.885
    assert lookup_cuisine_score({"italian": 0.885}, "Italian") == 0.885
    assert lookup_cuisine_score({"India": 0.7}, "Indian") == 0.7
    assert lookup_cuisine_score({"Italian": 0.885}, "Thai") == 0.5
    assert lookup_cuisine_score({"Italian": 0.885}, None) == 0.5
    merged, points = collapse_cuisine_scores({"italian": 0.8, "Italian": 0.4}, {"italian": 3, "Italian": 1})
    assert merged == {"Italian": pytest.approx(0.7)} and points == {"Italian": 4}
