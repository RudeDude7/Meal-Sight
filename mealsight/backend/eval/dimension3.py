"""Dimension 3: match accuracy. When the matcher reports a score, is it right?

Runs the production matcher (mealsight.matching.matcher.match_recipe_by_id, the
function behind the match_ingredients tool the pipeline calls) on 30 cases whose
expected outcomes were derived BY HAND (eval/cases3.py explains how), and compares:

  * score          the reported numeric score against the hand-computed one, within
                   SCORE_TOLERANCE (the matcher rounds to 4 decimals);
  * classification which ingredients are matched / substitutable / partial / missing,
                   and which are critical-missing, as exact multisets of canonical names.

A case where the score lands right but an ingredient is misclassified FAILS: the score
is the summary of the classification, and a coincidence of arithmetic is not accuracy.
can_cook and the avoid-list exclusion are checked too.

Two steps are not inside match_recipe and are applied exactly as the pipeline applies
them: long-expired pantry items are dropped with usable_pantry_names, and avoid lists
exclude with mealsight.matching.avoid. No API calls are made.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from eval.cases3 import MATCH_CASES, MatchCase
from eval.models import DimensionResult, MatchCaseResult
from mealsight.agent.reasoning_facts import _recipe_ingredient_names
from mealsight.db import get_recipe_db
from mealsight.matching.avoid import ingredient_hits
from mealsight.matching.matcher import build_match_context, match_recipe_by_id
from mealsight.pantry.expiring import usable_pantry_names

NAME = "dimension3_match_accuracy"
PASS_THRESHOLD = 1.0  # arithmetic on fixed inputs: any disagreement is a real finding
SCORE_TOLERANCE = 0.001


def _actual_buckets(result: Any) -> dict[str, Any]:
    return {
        "matched": sorted(item.name for item in result.matched_items),
        "substitutable": sorted((item.original, item.substitute) for item in result.substitutable_items),
        "partial": sorted((item.name, item.pantry_match) for item in result.partial_matches),
        "missing": sorted(item.name for item in result.missing_items),
        "critical_missing": sorted(result.critical_missing),
    }


def _expected_buckets(case: MatchCase) -> dict[str, Any]:
    return {
        "matched": sorted(case.expected_matched),
        "substitutable": sorted(case.expected_substitutable),
        "partial": sorted(case.expected_partial),
        "missing": sorted(case.expected_missing),
        "critical_missing": sorted(case.expected_critical_missing),
    }


def diff_buckets(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for bucket in ("matched", "substitutable", "partial", "missing", "critical_missing"):
        want, got = (
            Counter(map(tuple, [(x,) if isinstance(x, str) else x for x in expected[bucket]])),
            Counter(map(tuple, [(x,) if isinstance(x, str) else x for x in actual[bucket]])),
        )
        if want != got:
            only_expected = sorted((want - got).elements())
            only_actual = sorted((got - want).elements())
            out.append(f"{bucket}: expected-only {only_expected}, matcher-only {only_actual}")
    return out


def score_case(
    case: MatchCase,
    actual_score: float | None,
    actual: dict[str, Any],
    actual_can_cook: bool | None,
    actual_excluded: bool,
) -> MatchCaseResult:
    expected = _expected_buckets(case)
    disagreements = diff_buckets(expected, actual) if actual_score is not None else ["no result"]
    classification_ok = not disagreements
    score_ok = actual_score is not None and abs(actual_score - case.expected_score) <= SCORE_TOLERANCE
    can_cook_ok = actual_can_cook == case.expected_can_cook
    exclusion_ok = actual_excluded == case.expected_excluded_by_avoid
    if not score_ok:
        disagreements.append(f"score: expected {case.expected_score}, matcher {actual_score}")
    if not can_cook_ok:
        disagreements.append(f"can_cook: expected {case.expected_can_cook}, matcher {actual_can_cook}")
    if not exclusion_ok:
        disagreements.append(
            f"avoid exclusion: expected excluded={case.expected_excluded_by_avoid}, got {actual_excluded}"
        )
    return MatchCaseResult(
        case_id=case.case_id,
        description=case.description,
        recipe_id=case.recipe_id,
        recipe_name=case.recipe_name,
        paths=list(case.paths),
        basis=case.basis,
        expected_score=case.expected_score,
        actual_score=actual_score,
        score_ok=score_ok,
        classification_ok=classification_ok,
        can_cook_ok=can_cook_ok,
        exclusion_ok=exclusion_ok,
        passed=score_ok and classification_ok and can_cook_ok and exclusion_ok,
        expected={
            **expected,
            "score": case.expected_score,
            "can_cook": case.expected_can_cook,
            "excluded_by_avoid": case.expected_excluded_by_avoid,
        },
        actual={
            **actual,
            "score": actual_score,
            "can_cook": actual_can_cook,
            "excluded_by_avoid": actual_excluded,
        },
        disagreements=disagreements,
        derivation=case.derivation + (f" {case.corrections}" if case.corrections else ""),
    )


async def run_dimension3(case_limit: int | None = None) -> DimensionResult:
    cases = MATCH_CASES[:case_limit] if case_limit is not None else MATCH_CASES
    start = time.monotonic()
    db = get_recipe_db()
    context = await build_match_context(db)
    results: list[MatchCaseResult] = []
    try:
        for case in cases:
            row = await db.fetch_one("SELECT name FROM recipes WHERE id = ?", (case.recipe_id,))
            if row is None or str(row["name"]).strip() != case.recipe_name.strip():
                # A case written against a recipe that is not there is a broken case, not a matcher result.
                raise AssertionError(
                    f"{case.case_id}: recipe {case.recipe_id} is {row and row['name']!r}, "
                    f"expected {case.recipe_name!r}"
                )
            pantry = [
                {"name": e, "days_remaining": None}
                if isinstance(e, str)
                else {"name": e[0], "days_remaining": e[1]}
                for e in case.pantry
            ]
            names = usable_pantry_names(pantry)
            result = await match_recipe_by_id(
                db, case.recipe_id, names, list(case.restrictions) or None, context
            )
            excluded = bool(
                case.avoid
                and ingredient_hits(list(case.avoid), _recipe_ingredient_names(result.model_dump()))
            )
            results.append(
                score_case(case, result.match_score, _actual_buckets(result), result.can_cook, excluded)
            )
    finally:
        await db.close()

    n = len(results)
    passed = sum(1 for r in results if r.passed)
    by_path: dict[str, list[int]] = {}
    for r in results:
        for path in r.paths:
            counts = by_path.setdefault(path, [0, 0])
            counts[1] += 1
            counts[0] += int(r.passed)
    return DimensionResult(
        name=NAME,
        pass_threshold=PASS_THRESHOLD,
        score=passed / n if n else 0.0,
        passed=n > 0 and passed == n,
        metrics={
            "cases_passed": passed,
            "cases_total": n,
            "score_accuracy": sum(r.score_ok for r in results) / n if n else 0.0,
            "classification_accuracy": sum(r.classification_ok for r in results) / n if n else 0.0,
            "can_cook_accuracy": sum(r.can_cook_ok for r in results) / n if n else 0.0,
            "exclusion_accuracy": sum(r.exclusion_ok for r in results) / n if n else 0.0,
            "score_correct_but_misclassified": [
                r.case_id for r in results if r.score_ok and not r.classification_ok
            ],
            "score_tolerance": SCORE_TOLERANCE,
            "disagreeing_cases": [r.case_id for r in results if not r.passed],
            "by_path_passed_of_total": {p: f"{a}/{b}" for p, (a, b) in sorted(by_path.items())},
            "by_basis": {
                basis: f"{sum(1 for r in results if r.basis == basis and r.passed)}/"
                f"{sum(1 for r in results if r.basis == basis)}"
                for basis in sorted({r.basis for r in results})
            },
        },
        case_count=n,
        api_calls=0,
        total_tokens=0,
        wall_clock_seconds=time.monotonic() - start,
        match_case_results=results,
    )
