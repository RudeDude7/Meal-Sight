"""The Dimension 3 scorer itself, with known answers (no database, no matcher)."""

from eval.cases3 import MATCH_CASES, MatchCase
from eval.dimension3 import SCORE_TOLERANCE, diff_buckets, score_case


def _case(**kw: object) -> MatchCase:
    base: dict[str, object] = {
        "case_id": "fx",
        "description": "fixture",
        "recipe_id": "1",
        "recipe_name": "R",
        "pantry": (),
        "expected_matched": ("a", "b"),
        "expected_missing": ("c",),
        "expected_score": 0.6667,
        "expected_can_cook": True,
        "derivation": "",
        "paths": (),
    }
    base.update(kw)
    return MatchCase(**base)  # type: ignore[arg-type]


_RIGHT = {"matched": ["a", "b"], "substitutable": [], "partial": [], "missing": ["c"], "critical_missing": []}


def test_a_matching_result_passes_every_check() -> None:
    r = score_case(_case(), 0.6667, _RIGHT, True, False)
    assert r.passed and r.score_ok and r.classification_ok and not r.disagreements


def test_right_score_with_a_misclassified_ingredient_fails() -> None:
    # Same numbers, different split: 'b' reported missing and 'c' matched. The score
    # happens to be identical, which is exactly the coincidence that must not pass.
    swapped = {**_RIGHT, "matched": ["a", "c"], "missing": ["b"]}
    r = score_case(_case(), 0.6667, swapped, True, False)
    assert r.score_ok and not r.classification_ok and not r.passed
    assert any(d.startswith("matched:") for d in r.disagreements)


def test_right_classification_with_a_wrong_score_fails() -> None:
    r = score_case(_case(), 0.5, _RIGHT, True, False)
    assert r.classification_ok and not r.score_ok and not r.passed


def test_score_tolerance_is_the_matchers_rounding() -> None:
    assert score_case(_case(), 0.6667 + SCORE_TOLERANCE / 2, _RIGHT, True, False).score_ok
    assert not score_case(_case(), 0.6667 + SCORE_TOLERANCE * 2, _RIGHT, True, False).score_ok


def test_can_cook_and_exclusion_are_checked() -> None:
    assert not score_case(_case(), 0.6667, _RIGHT, False, False).passed
    assert not score_case(_case(expected_excluded_by_avoid=True), 0.6667, _RIGHT, True, False).passed


def test_substitution_and_partial_pairs_are_compared_as_pairs() -> None:
    want = {**_RIGHT, "substitutable": [("milk", "oat milk")], "partial": [("chicken breast", "chicken")]}
    got = {**want, "substitutable": [("milk", "soy milk")]}
    assert diff_buckets(want, got)
    assert not diff_buckets(want, want)


def test_cases_are_well_formed_and_cover_every_required_path() -> None:
    assert len(MATCH_CASES) == 32
    paths = {p for c in MATCH_CASES for p in c.paths}
    required = {
        "exact",
        "synonym",
        "specificity_full",
        "specificity_partial",
        "protected_term",
        "substitution",
        "dietary_rejection",
        "critical_missing",
        "expired_excluded",
        "avoid_exclusion",
        "optional_gap",
    }
    assert required <= paths, f"paths with no case: {sorted(required - paths)}"
    for c in MATCH_CASES:
        n = (
            len(c.expected_matched)
            + len(c.expected_missing)
            + len(c.expected_substitutable)
            + len(c.expected_partial)
        )
        assert n > 0 or c.case_id == "d3_14" or c.expected_missing, c.case_id


def test_each_cases_expected_score_is_consistent_with_its_own_expected_classification() -> None:
    """Guards the hand derivations against arithmetic slips: applies the documented formula
    (not the matcher) to each case's own expected buckets."""
    for c in MATCH_CASES:
        total = (
            len(c.expected_matched)
            + len(c.expected_substitutable)
            + len(c.expected_partial)
            + len(c.expected_missing)
        )
        weighted = len(c.expected_matched) + 0.7 * (len(c.expected_substitutable) + len(c.expected_partial))
        score = max(0.0, min(1.0, weighted / total - 0.3 * len(c.expected_critical_missing)))
        assert abs(score - c.expected_score) <= 0.0001, (c.case_id, score, c.expected_score)
        assert c.expected_can_cook == (score >= 0.5 and not c.expected_critical_missing), c.case_id
