"""The regression gate (eval/compare.py): what fails the build, and what must not."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from eval.compare import BASELINE_PATH, build_baseline_update, compare, main

BASELINE = json.loads(BASELINE_PATH.read_text())
D1, D2, D3, D4, D5 = (
    "dimension1_ingredient_recognition",
    "dimension2_constraint_satisfaction",
    "dimension3_match_accuracy",
    "dimension4_freshness_prioritization",
    "dimension5_personalization",
)
INVARIANT_METRICS = {
    D2: {"total_violations": 0},
    D3: {"disagreeing_cases": [], "classification_accuracy": 1.0, "score_accuracy": 1.0},
    D4: {"case_defects": [], "real_data_untouched": True},
    D5: {"case_defects": [], "real_data_untouched": True},
}


def _scorecard(**overrides: Any) -> dict[str, Any]:
    """A scorecard that exactly reproduces the baseline, with per-dimension overrides applied."""
    dims = []
    for name, base in BASELINE["dimensions"].items():
        d: dict[str, Any] = {
            "name": name,
            "score": base["score"],
            "pass_threshold": base["threshold"],
            "case_count": base["case_count"],
            "passed": base["status"] != "known_failing" and base["score"] >= base["threshold"],
            "metrics": copy.deepcopy(INVARIANT_METRICS.get(name, {})),
        }
        d.update(overrides.get(name, {}))
        dims.append(d)
    return {
        "run_id": "run_test",
        **copy.deepcopy(BASELINE["provenance"]),
        "dimensions": dims,
        "pantry": {
            "pantry_present": True,
            "rows_at_run_start": BASELINE["provenance"]["pantry_rows"],
            "pantry_content_sha256": BASELINE["provenance"]["pantry_content_sha256"],
        },
    }


def _status(report: Any, name: str) -> str:
    return next(f.status for f in report.findings if f.dimension == name)


def test_a_scorecard_identical_to_the_baseline_passes_and_the_known_failure_is_not_an_alarm() -> None:
    report = compare(_scorecard(), BASELINE)
    assert report.passed
    assert _status(report, D1) == "KNOWN FAILING (at baseline)"
    assert all(_status(report, n) == "OK" for n in (D2, D3, D4, D5))


@pytest.mark.parametrize("score", [0.479, 0.485, 0.492, 0.497])
def test_dimension1_run_to_run_noise_does_not_trip_the_gate(score: float) -> None:
    report = compare(_scorecard(**{D1: {"score": score}}), BASELINE)
    assert report.passed, "the observed 0.485 to 0.492 spread must be inside the band"


def test_dimension1_dropping_well_below_its_known_level_is_a_regression() -> None:
    report = compare(_scorecard(**{D1: {"score": 0.43}}), BASELINE)
    assert not report.passed and _status(report, D1) == "REGRESSION"


def test_dimension1_recovering_past_its_threshold_is_reported_not_failed() -> None:
    report = compare(_scorecard(**{D1: {"score": 0.62, "passed": True}}), BASELINE)
    assert report.passed and _status(report, D1) == "RECOVERED"


def test_the_matcher_gate_has_no_tolerance() -> None:
    report = compare(_scorecard(**{D3: {"score": 0.9688}}), BASELINE)
    assert not report.passed and _status(report, D3) == "REGRESSION"


def test_any_hard_constraint_violation_fails_even_if_the_score_barely_moves() -> None:
    sc = _scorecard()
    next(d for d in sc["dimensions"] if d["name"] == D2)["metrics"]["total_violations"] = 1
    report = compare(sc, BASELINE)
    assert not report.passed
    assert "total_violations" in next(f for f in report.findings if f.dimension == D2).detail


def test_one_case_of_noise_in_the_model_dependent_dimensions_is_tolerated_two_are_not() -> None:
    assert compare(_scorecard(**{D4: {"score": 0.8667}}), BASELINE).passed
    assert not compare(_scorecard(**{D4: {"score": 0.8}}), BASELINE).passed
    assert compare(_scorecard(**{D5: {"score": 0.9444}}), BASELINE).passed
    assert not compare(_scorecard(**{D5: {"score": 0.8889}}), BASELINE).passed


def test_a_lowered_pass_threshold_is_a_regression_even_if_the_score_is_unchanged() -> None:
    report = compare(_scorecard(**{D1: {"pass_threshold": 0.45}}), BASELINE)
    assert not report.passed
    assert "threshold changed" in next(f for f in report.findings if f.dimension == D1).detail


def test_silently_dropped_cases_or_a_missing_dimension_fail() -> None:
    assert not compare(_scorecard(**{D5: {"case_count": 15}}), BASELINE).passed
    sc = _scorecard()
    sc["dimensions"] = [d for d in sc["dimensions"] if d["name"] != D4]
    report = compare(sc, BASELINE)
    assert not report.passed and _status(report, D4) == "REGRESSION"


def test_extra_cases_are_a_note_not_a_failure() -> None:
    report = compare(_scorecard(**{D5: {"case_count": 20}}), BASELINE)
    assert report.passed and any("refresh it" in n for n in report.notes)


def test_a_real_database_being_touched_fails_the_isolated_dimensions() -> None:
    sc = _scorecard()
    next(d for d in sc["dimensions"] if d["name"] == D5)["metrics"]["real_data_untouched"] = False
    assert not compare(sc, BASELINE).passed


def test_only_limits_the_comparison_to_the_named_dimension() -> None:
    sc = _scorecard(**{D1: {"score": 0.1}})
    assert compare(sc, BASELINE, only={"dimension3"}).passed
    assert len(compare(sc, BASELINE, only={"dimension3"}).findings) == 1


def test_strict_data_fails_when_the_rebuilt_reference_data_differs() -> None:
    sc = _scorecard()
    sc["data_versions"]["recipe_corpus"] = "000000000000"
    assert compare(sc, BASELINE).passed, "without --strict-data a provenance difference is only a note"
    assert any("recipe_corpus" in n for n in compare(sc, BASELINE).notes)
    strict = compare(sc, BASELINE, strict_data=True)
    assert not strict.passed and "recipe_corpus" in strict.findings[-1].detail


def test_refreshing_the_baseline_keeps_tolerances_and_statuses() -> None:
    sc = _scorecard(**{D4: {"score": 1.0}, D1: {"score": 0.51}})
    new = build_baseline_update(sc, BASELINE, "test")
    assert new["dimensions"][D4]["score"] == 1.0
    assert new["dimensions"][D4]["tolerance"] == BASELINE["dimensions"][D4]["tolerance"]
    assert new["dimensions"][D1]["status"] == "known_failing"  # a score alone does not relabel it
    assert new["update_reason"] == "test"


def test_cli_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_scorecard()))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_scorecard(**{D3: {"score": 0.5}})))
    assert main([str(good)]) == 0
    assert main([str(bad)]) == 1
    assert main([str(tmp_path / "missing.json")]) == 2, "a gate that cannot run must not read as passing"
    assert main([str(good), "--update"]) == 2, "--update needs a reason"


def test_the_committed_baseline_is_well_formed() -> None:
    assert set(BASELINE["dimensions"]) == {D1, D2, D3, D4, D5}
    for name, base in BASELINE["dimensions"].items():
        assert {"score", "threshold", "case_count", "tolerance", "status", "reason"} <= set(base), name
    assert BASELINE["dimensions"][D1]["status"] == "known_failing"
    assert BASELINE["dimensions"][D3]["tolerance"] == 0.0


def test_an_absent_or_different_pantry_fails_the_pantry_dependent_dimensions_strictly() -> None:
    absent = _scorecard()
    absent["pantry"] = {"pantry_present": False, "rows_at_run_start": None, "pantry_content_sha256": None}
    strict = compare(absent, BASELINE, strict_data=True)
    assert not strict.passed
    assert "ABSENT" in next(f.detail for f in strict.findings if f.dimension == "provenance")
    other = _scorecard()
    other["pantry"]["pantry_content_sha256"] = "000000000000"
    assert not compare(other, BASELINE, strict_data=True).passed


def test_the_matcher_gate_does_not_need_a_pantry() -> None:
    """Dimension 3 carries its own pantry state: an absent pantry is a note there, never a failure."""
    absent = _scorecard()
    absent["pantry"] = {"pantry_present": False, "rows_at_run_start": None, "pantry_content_sha256": None}
    report = compare(absent, BASELINE, only={"dimension3"}, strict_data=True)
    assert report.passed
    assert any("pantry content" in n for n in report.notes)
