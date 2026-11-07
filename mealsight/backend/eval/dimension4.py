"""Dimension 4: freshness prioritization. When an ingredient is near expiry, does the
recommendation use it? See eval/cases4.py for the verdict rules and how the expected outcomes
were derived. Each case runs the real pipeline against a throwaway pantry (eval/isolation.py).
"""

from __future__ import annotations

import time
from typing import Any

from eval.analysis import Candidate, analyse, composite, load_corpus, uses_item
from eval.cases4 import FRESHNESS_CASES, FreshnessCase
from eval.isolation import IsolatedWorld, file_fingerprints
from eval.models import DimensionResult, ScenarioCaseResult
from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.runner import run_recommendation
from mealsight.providers import get_text_provider

NAME = "dimension4_freshness_prioritization"
PASS_THRESHOLD = 0.80  # fixed before the first run: 12 of 15
# Independent copies of the documented rules (see eval/cases4.py): expiring means 3 days or fewer left,
# and more than 2 days past the shelf life is waste.
EXPIRING_SOON_DAYS = 3
GRACE_DAYS = 2
DEFAULT_TIME_MINUTES = 30  # the profile default applies: these cases state no time


def classify_situation(cooks: list[Candidate]) -> str:
    users = [c for c in cooks if c.uses_expiring]
    if not users:
        return "no_opportunity"
    best_user = max(c.composite for c in users)
    if any(c.composite > best_user for c in cooks if not c.uses_expiring):
        return "justified_deprioritization"
    return "must_prioritize"


def verdict_for(recommended: Candidate | None, cooks: list[Candidate]) -> tuple[str, str]:
    users = [c for c in cooks if c.uses_expiring]
    if not users:
        return (
            "no_opportunity",
            "No cookable recipe uses an expiring, usable item, so there was nothing to prioritize.",
        )
    best_user = max(users, key=lambda c: c.composite)
    if recommended is None:
        return "failed_to_prioritize", (
            f"The system recommended nothing although {len(users)} cookable recipe(s) used an expiring item "
            f"(best: {best_user.name}, composite {best_user.composite})."
        )
    if recommended.uses_expiring:
        return "used", f"{recommended.name} uses expiring {recommended.uses_expiring}."
    rec, best = recommended, best_user
    if rec.composite > best.composite:
        return "justified_deprioritization", (
            f"{rec.name} (composite {rec.composite}) legitimately beats the best expiring-item "
            f"recipe, {best.name} (composite {best.composite}): a stronger match outweighs "
            "the freshness bonus."
        )
    return "failed_to_prioritize", (
        f"{rec.name} (composite {rec.composite}, uses no expiring item) was recommended although "
        f"{best.name} (composite {best.composite}) uses {best.uses_expiring} and scores at least as well."
    )


async def _run_case(case: FreshnessCase, world: IsolatedWorld, corpus: Any) -> ScenarioCaseResult:
    reset = await world.reset()
    await world.seed_pantry(list(case.pantry))
    readback = await world.verify_pantry(list(case.pantry))

    # What was possible, computed independently of the pipeline.
    days = {i.name: i.days_remaining for i in case.pantry}
    waste = sorted(n for n, d in days.items() if d is not None and d < -GRACE_DAYS)
    expiring = sorted(
        n for n, d in days.items() if d is not None and d <= EXPIRING_SOON_DAYS and n not in waste
    )
    usable = [i.name for i in case.pantry if i.name not in waste]
    cands = analyse(corpus, usable, expiring)
    cooks = [c for c in cands if c.can_cook]
    for c in cooks:
        c.composite = composite(c, default_time_minutes=DEFAULT_TIME_MINUTES)
    cooks.sort(key=lambda c: -c.composite)
    situation = classify_situation(cooks)

    # The system under test.
    async with MCPClientManager(env=world.env) as manager:
        state = await run_recommendation(
            text_input=case.request, manager=manager, trace_id=f"eval-d4-{case.case_id}"
        )
    top = state.get("top_recommendation") or {}
    available = bool(top.get("available"))
    rec_id = top.get("recipe_id") if available else None
    by_id = {c.recipe_id: c for c in cands}
    recommended = by_id.get(str(rec_id)) if rec_id else None
    if recommended is not None and not recommended.can_cook:
        recommended = None  # an uncookable recommendation is no use to anyone

    reported_expiring = sorted(str(i.get("name")) for i in state.get("expiring_items") or [])
    reported_waste = sorted(str(i.get("name")) for i in state.get("waste_candidates") or [])
    expiring_ok = reported_expiring == sorted(case.expected_expiring) and not set(case.expected_waste) & set(
        reported_expiring
    )
    waste_ok = reported_waste == sorted(case.expected_waste)

    verdict, reason = verdict_for(recommended, cooks)
    system_ok = verdict != "failed_to_prioritize"
    case_defect = None
    if situation != case.expected_situation:
        case_defect = (
            f"designed as {case.expected_situation} but the pantry produces {situation} "
            f"(cookable users of an expiring item: {[c.name for c in cooks if c.uses_expiring][:4]})"
        )
    if sorted(expiring) != sorted(case.expected_expiring) or waste != sorted(case.expected_waste):
        case_defect = (
            case_defect or ""
        ) + f" | derived expiring {expiring} / waste {waste} differ from the case"

    # Mechanism: did match_rank's freshness flag agree with an independent "uses an expiring item"?
    flag_checks = []
    for r in state.get("matched_recipes") or []:
        cand = by_id.get(str(r.get("recipe_id")))
        if cand is None or not cand.can_cook:
            continue
        want = bool(cand.uses_expiring)
        got = bool(r.get("uses_expiring_ingredient"))
        flag_checks.append(
            {"recipe": cand.name, "expected_flag": want, "system_flag": got, "ok": want == got}
        )
    bad_flags = [f for f in flag_checks if not f["ok"]]

    explanation = reason
    if not expiring_ok:
        explanation += (
            f" EXPIRING LIST WRONG: reported {reported_expiring}, expected {sorted(case.expected_expiring)}."
        )
    if not waste_ok:
        explanation += (
            f" WASTE LIST WRONG: reported {reported_waste}, expected {sorted(case.expected_waste)}."
        )
    if bad_flags:
        explanation += " FRESHNESS FLAG DISAGREES for: " + "; ".join(
            f"{f['recipe']} (should be {f['expected_flag']}, system said {f['system_flag']})"
            for f in bad_flags
        )
    passed = system_ok and expiring_ok and waste_ok and case_defect is None
    return ScenarioCaseResult(
        case_id=case.case_id,
        description=case.description,
        paths=list(case.paths),
        expected={
            "situation": case.expected_situation,
            "expiring": list(case.expected_expiring),
            "waste": list(case.expected_waste),
        },
        actual={
            "situation": situation,
            "recommended": recommended.name if recommended else None,
            "recommended_composite": recommended.composite if recommended else None,
            "reported_expiring": reported_expiring,
            "reported_waste": reported_waste,
            "cookable_count": len(cooks),
            "top_by_hand_composite": [(c.name, c.composite, c.uses_expiring) for c in cooks[:4]],
        },
        verdict=verdict,
        passed=passed,
        explanation=explanation,
        case_defect=case_defect,
        diagnostics={
            "flag_checks": flag_checks,
            "pantry_readback": readback,
            # What the system's own ranking said, against what the reasoning step finally chose.
            "system_ranking": [
                (
                    r.get("name"),
                    r.get("composite_score"),
                    r.get("match_score"),
                    r.get("uses_expiring_ingredient"),
                )
                for r in (state.get("matched_recipes") or [])[:4]
            ],
            "model_freshness_reasoning": ((top.get("reasoning") or {}).get("freshness_reasoning") or {}).get(
                "reasoning"
            ),
            "reason_message": next(
                (m for m in state.get("stream_messages", []) if m.startswith("[reason]")), None
            ),
        },
        reset_verification={
            "tables_after_reset": len(reset),
            "all_empty": all(v == 0 for v in reset.values()),
        },
    )


async def run_dimension4(case_limit: int | None = None) -> DimensionResult:
    cases = FRESHNESS_CASES[:case_limit] if case_limit is not None else FRESHNESS_CASES
    start = time.monotonic()
    before = file_fingerprints()
    corpus = await load_corpus()
    world = IsolatedWorld()
    results: list[ScenarioCaseResult] = []
    try:
        for case in cases:
            results.append(await _run_case(case, world, corpus))
    finally:
        await world.cleanup()
    after = file_fingerprints()
    real_data_untouched = before == after

    n = len(results)
    passed = sum(1 for r in results if r.passed)
    opportunity = [r for r in results if r.verdict != "no_opportunity"]
    flag_checks = [f for r in results for f in r.diagnostics.get("flag_checks", [])]
    tokens = sum(
        int(call.get("total_tokens", 0))
        for call in get_text_provider().get_call_log()
        if str(call.get("trace_id", "")).startswith("eval-d4-")
    )
    score = passed / n if n else 0.0
    return DimensionResult(
        name=NAME,
        pass_threshold=PASS_THRESHOLD,
        score=score,
        passed=n > 0 and score >= PASS_THRESHOLD and real_data_untouched,
        metrics={
            "cases_passed": passed,
            "cases_total": n,
            "pass_threshold": PASS_THRESHOLD,
            "verdicts": {
                v: sum(1 for r in results if r.verdict == v) for v in sorted({r.verdict for r in results})
            },
            "opportunity_cases": len(opportunity),
            "opportunity_cases_passed": sum(1 for r in opportunity if r.passed),
            "failed_to_prioritize": [r.case_id for r in results if r.verdict == "failed_to_prioritize"],
            "case_defects": [r.case_id for r in results if r.case_defect],
            "expiring_list_errors": [r.case_id for r in results if "LIST WRONG" in r.explanation],
            "freshness_flag_accuracy": (
                sum(1 for f in flag_checks if f["ok"]) / len(flag_checks) if flag_checks else None
            ),
            "freshness_flag_checks": len(flag_checks),
            "freshness_flag_wrong": sorted({r.case_id for r in results if "FLAG DISAGREES" in r.explanation}),
            "real_data_untouched": real_data_untouched,
            "real_db_fingerprints": after,
        },
        case_count=n,
        api_calls=n,
        total_tokens=tokens,
        wall_clock_seconds=time.monotonic() - start,
        scenario_case_results=results,
    )


__all__ = ["run_dimension4", "uses_item"]
