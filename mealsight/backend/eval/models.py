"""Typed shapes for the eval framework's own scorecard — one Scorecard
per run, written as JSON to eval/results/, with enough recorded about
the run itself (model IDs, prompt versions, git commit, timestamp) that
two scorecards can be meaningfully compared later."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["hard", "soft"]


class Violation(BaseModel):
    """One broken hard constraint, named specifically enough to debug
    without re-running anything — the case, the exact constraint, and
    what was actually recommended instead of a bare failure count."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    constraint: str
    detail: str
    recommended_recipe_id: str | None
    recommended_recipe_name: str | None


class CaseResult(BaseModel):
    """One Dimension 2 case's own outcome. passed is True either when
    every hard constraint held against a real recommendation, OR the
    system honestly refused to recommend anything — both are correct
    behavior; only a violating recommendation, or a refusal on a case
    that was actually satisfiable, fails."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    description: str
    text_input: str
    expect_refusal: bool
    actual_refusal: bool
    passed: bool
    violations: list[Violation]
    soft_score: float | None
    recipe_id: str | None
    recipe_name: str | None
    notes: str
    # What was enforced (authored plus extracted) and what the recommended
    # recipe actually has, so a result can be audited without re-running.
    constraints_checked: dict[str, Any] = {}
    recipe_facts: dict[str, Any] = {}


class ImageResult(BaseModel):
    """One Dimension 1 photo's own scored result."""

    model_config = ConfigDict(frozen=True)

    photo_id: str
    predicted_items: list[str]
    ground_truth_items: list[str]
    precision: float
    recall_raw: float
    recall_adjusted: float
    f1_raw: float
    f1_adjusted: float
    error: str | None


class MatchCaseResult(BaseModel):
    """One Dimension 3 case: the hand-derived expectation next to what the matcher produced,
    scored on the numeric score and on the per-ingredient classification SEPARATELY."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    description: str
    recipe_id: str
    recipe_name: str
    paths: list[str]
    basis: str
    expected_score: float
    actual_score: float | None
    score_ok: bool
    classification_ok: bool
    can_cook_ok: bool
    exclusion_ok: bool
    passed: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    disagreements: list[str] = []
    derivation: str = ""


class ScenarioCaseResult(BaseModel):
    """One Dimension 4 or 5 case: a state the system was put in, what it was asked, what was
    possible, what it recommended, and the verdict with the reason."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    description: str
    paths: list[str]
    expected: dict[str, Any]
    actual: dict[str, Any]
    verdict: str
    passed: bool
    explanation: str
    # Set when the case's own design did not produce the situation its derivation claimed. That is a
    # defect in the case, reported as such, never counted as a system failure.
    case_defect: str | None = None
    diagnostics: dict[str, Any] = {}
    reset_verification: dict[str, Any] = {}


class DimensionResult(BaseModel):
    """One dimension's own full result — its own declared pass
    threshold, whether it cleared it, dimension-specific aggregate
    metrics, and full per-case/per-image detail so a failure is
    debuggable from the scorecard alone."""

    model_config = ConfigDict(frozen=True)

    name: str
    pass_threshold: float
    score: float
    passed: bool
    metrics: dict[str, Any]
    case_count: int
    api_calls: int
    total_tokens: int
    wall_clock_seconds: float
    image_results: list[ImageResult] = []
    case_results: list[CaseResult] = []
    match_case_results: list[MatchCaseResult] = []
    scenario_case_results: list[ScenarioCaseResult] = []


class Scorecard(BaseModel):
    """The full JSON artifact one eval run produces — written to
    eval/results/{run_id}.json. Reproducibility fields (model_ids,
    prompt_versions, git_commit, timestamp) are recorded on every run,
    even a partial/sampled one, so two scorecards can be compared
    later without guessing what configuration produced either one."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    timestamp: str
    git_commit: str
    model_ids: dict[str, str]
    prompt_versions: dict[str, str]
    # Lexicons, rule sets and constants in code that shape results (eval/provenance.py), and the
    # reference tables read at run time. Recorded separately so a changed result can be traced.
    component_versions: dict[str, str] = {}
    data_versions: dict[str, str] = {}
    dimensions: list[DimensionResult]
    passed: bool
    # What the pantry looked like when this run started. Dimensions 3-5 only
    # mean something relative to it, so it is recorded with the numbers.
    pantry: dict[str, Any] = {}
    # Traceable scorer/methodology changes that make this run's numbers
    # non-comparable with earlier published ones.
    notes: list[str] = []
    # The commit hash alone does not identify the code under test when the
    # working tree has uncommitted changes.
    git_dirty: bool = False
    git_diff_sha256: str = ""
    # An aborted run is an infrastructure failure (eval/circuit.py), never a quality result. The regression
    # gate refuses to compare against it or to record it as a baseline.
    aborted: bool = False
    abort_reason: str | None = None
    abort_detail: dict[str, Any] = {}
