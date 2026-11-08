"""Dimension 5: personalization. After a profile is seeded, do recommendations align with it?
See eval/cases5.py for the design, the recipe pairs, the hand derivations and the verdict rules.
Each case runs the real pipeline against a throwaway pantry and a freshly seeded profile.
"""

from __future__ import annotations

import time
from typing import Any

from eval.analysis import Candidate, analyse, canonical, composite, load_corpus
from eval.cases5 import PERSONALIZATION_CASES, Aspect, PersonalizationCase
from eval.circuit import breaker
from eval.dimension2 import ingredient_hits, restriction_violations
from eval.isolation import IsolatedWorld, PantrySeed, file_fingerprints
from eval.models import DimensionResult, ScenarioCaseResult
from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.runner import run_recommendation
from mealsight.matching.protein import names_include_protein
from mealsight.providers import get_text_provider

NAME = "dimension5_personalization"
PASS_THRESHOLD = 0.80  # fixed before the first run: 12 of 15
WINDOW_DAYS = 7
MAX_SAME_PROTEIN = 3


def in_aligned_set(aspect: Aspect, cand: Candidate) -> bool:
    kind, value = aspect.kind, aspect.value
    if kind == "cuisine":
        return (cand.cuisine or "").lower() == str(value).lower()
    if kind == "dislike":
        return not ingredient_hits([str(value)], cand.ingredient_names)
    if kind == "restriction":
        # Tag-backed restrictions: the corpus tags. The rest: this scorer's OWN ingredient rules.
        if str(value) in ("vegetarian", "vegan", "dairy_free", "gluten_free", "nut_free"):
            return str(value) in cand.tags
        return not restriction_violations(str(value), cand.ingredient_names)
    if kind == "protein":
        return names_include_protein(cand.ingredient_names, str(value))
    if kind == "quick":
        return cand.cook_time is not None and cand.cook_time <= int(value)
    if kind == "repeat_recipe":
        return cand.recipe_id != str(value)
    if kind == "repeat_protein":
        return not names_include_protein(cand.ingredient_names, str(value))
    return True  # soft_time, household: not a subset question


def repetition_score(case: PersonalizationCase, cand: Candidate) -> float:
    """Hand rules: exact repeat in the window 1.0; else the candidate's protein already in more than
    MAX_SAME_PROTEIN window meals 0.7; else 0."""
    window = [m for m in case.profile.meals if m.days_ago <= WINDOW_DAYS]
    if any(m.recipe_id == cand.recipe_id for m in window if m.recipe_id):
        return 1.0
    for protein in ("chicken", "beef", "pork", "salmon", "fish"):
        if names_include_protein(cand.ingredient_names, protein):
            n = sum(1 for m in window if any(protein in u for u in m.ingredients_used))
            if n > MAX_SAME_PROTEIN:
                return 0.7
            break
    return 0.0


def verdict_for(
    case: PersonalizationCase, recommended: Candidate | None, cooks: list[Candidate]
) -> tuple[str, str, bool]:
    aspect = case.aspect
    if aspect.kind == "soft_time":
        ok = recommended is not None
        return (
            ("aligned" if ok else "misaligned"),
            (
                f"Recommended {recommended.name} ({recommended.cook_time} min) despite a "
                f"{aspect.value}-minute preference."
                if recommended
                else "Refused: a preferred cook time was treated as a limit although cookable recipes exist."
            ),
            ok,
        )
    if aspect.kind == "dislike_fallback":
        ok = recommended is not None
        return (
            ("aligned" if ok else "misaligned"),
            (
                f"Recommended {recommended.name} although it contains the disliked ingredient, "
                "because nothing else was cookable."
                if recommended
                else "Refused: a saved dislike was treated like an allergy and left the user with nothing."
            ),
            ok,
        )
    good = [c for c in cooks if in_aligned_set(aspect, c)]
    if not good:
        return "no_feasible_option", "No cookable recipe honours the signal.", True
    if recommended is None:
        return "misaligned", "Nothing was recommended although aligned recipes were cookable.", False
    if in_aligned_set(aspect, recommended):
        return "aligned", f"{recommended.name} honours the {aspect.kind} signal ({aspect.value}).", True
    best = max(good, key=lambda c: c.composite)
    if aspect.kind in ("cuisine", "protein", "quick") and recommended.composite > best.composite:
        return (
            "justified",
            (
                f"{recommended.name} (composite {recommended.composite}) legitimately beats the best aligned "
                f"recipe, {best.name} ({best.composite})."
            ),
            True,
        )
    return (
        "misaligned",
        (
            f"{recommended.name} (composite {recommended.composite}) was recommended although it does not "
            f"honour the {aspect.kind} signal ({aspect.value}) and {best.name} "
            f"(composite {best.composite}) does."
        ),
        False,
    )


async def _run_case(case: PersonalizationCase, world: IsolatedWorld, corpus: Any) -> ScenarioCaseResult:
    by_id = {r["id"]: r for r in corpus.rows}
    names: list[str] = []
    for rid in case.pantry.recipes:
        for n in by_id[rid]["ingredient_names"]:
            canon = canonical(n, corpus)
            if canon not in names:
                names.append(canon)
    names += [n for n in case.pantry.extra if n not in names]
    pantry = [PantrySeed(n) for n in names]

    reset = await world.reset()
    await world.seed_pantry(pantry)
    await world.verify_pantry(pantry)
    await world.seed_profile(case.profile)
    profile_readback = await world.verify_profile(case.profile)

    pref_minutes = int(profile_readback["preferred_cook_time_minutes"])
    cands = analyse(corpus, names, [])
    cooks = [c for c in cands if c.can_cook]
    for c in cooks:
        protein_pref = case.profile.protein_preference
        c.composite = composite(
            c,
            cuisine_scores=profile_readback["cuisine_scores"],
            protein_hit=bool(protein_pref) and names_include_protein(c.ingredient_names, protein_pref or ""),
            default_time_minutes=pref_minutes,
            repetition_score=repetition_score(case, c),
        )
    cooks.sort(key=lambda c: -c.composite)

    async with MCPClientManager(env=world.env) as manager:
        state = await run_recommendation(
            text_input=case.request, manager=manager, trace_id=f"eval-d5-{case.case_id}"
        )
    top = state.get("top_recommendation") or {}
    available = bool(top.get("available"))
    rec_id = top.get("recipe_id") if available else None
    by_cand = {c.recipe_id: c for c in cands}
    recommended = by_cand.get(str(rec_id)) if rec_id else None
    if recommended is not None and not recommended.can_cook:
        recommended = None
    unified = state.get("unified_request")
    servings = getattr(unified, "servings", None)
    scaled = (state.get("scaled_recipe") or {}).get("target_servings")

    if case.aspect.kind == "household":
        ok = servings == case.expected_servings and (recommended is None or scaled == case.expected_servings)
        verdict = "aligned" if ok else "misaligned"
        reason = f"servings {servings} (expected {case.expected_servings}); recipe scaled to {scaled}."
        passed_system = ok
    else:
        verdict, reason, passed_system = verdict_for(case, recommended, cooks)

    # Case design check: the hand-derived aligned recipes must really be cookable and in the aligned set,
    # and the hand-best recipe must be aligned for the tie-breaker cases.
    case_defect = None
    if case.aspect.kind != "household":
        good_names = {c.name for c in cooks if in_aligned_set(case.aspect, c)}
        missing = [n for n in case.aligned if n not in good_names]
        best_default = cooks[0] if cooks else None
        if missing:
            case_defect = f"hand-derived aligned recipes not cookable/aligned in this pantry: {missing}"
        elif best_default is not None and case.aspect.kind in ("dislike", "restriction"):
            # A dislike case is only meaningful if default scoring would pick the DISLIKED recipe.
            if best_default.name in case.aligned:
                case_defect = (
                    f"the case does not discriminate: default scoring already prefers the aligned recipe "
                    f"{best_default.name}"
                )
        elif (
            best_default is not None
            and case.aligned
            and case.aspect.kind not in ("soft_time", "dislike_fallback")
            and best_default.name not in case.aligned
        ):
            case_defect = (
                f"by the hand composite the best recipe is {best_default.name} ({best_default.composite}), "
                f"not the intended {list(case.aligned)}"
            )

    ranked = state.get("matched_recipes") or []
    ranking_first_aligned: bool | None = None
    if ranked and case.aspect.kind not in ("household", "soft_time", "dislike_fallback"):
        first_cand = by_cand.get(str(ranked[0].get("recipe_id")))
        ranking_first_aligned = in_aligned_set(case.aspect, first_cand) if first_cand else None
    ranking = [
        (r.get("name"), r.get("composite_score"), r.get("cuisine"), r.get("cook_time_minutes"))
        for r in ranked[:4]
    ]
    # Does the system's own ranking put the right recipe first, with the score the hand composite gives it?
    # Dislikes and restrictions are enforced by REMOVING candidates in code rather than by a score term, so
    # for those the hand ranking is taken over the recipes that remain allowed.
    hand_pool = (
        [c for c in cooks if in_aligned_set(case.aspect, c)]
        if case.aspect.kind in ("dislike", "restriction")
        else cooks
    )
    ranking_matches_hand: bool | None = None
    if case.aspect.kind not in ("household", "soft_time", "dislike_fallback") and hand_pool and ranked:
        ranking_matches_hand = (
            ranked[0].get("name") == hand_pool[0].name
            and abs(float(ranked[0].get("composite_score") or 0) - hand_pool[0].composite) <= 0.002
        )
    return ScenarioCaseResult(
        case_id=case.case_id,
        description=case.description,
        paths=list(case.paths),
        expected={
            "aligned": list(case.aligned),
            "servings": case.expected_servings,
            "aspect": f"{case.aspect.kind}={case.aspect.value}",
        },
        actual={
            "recommended": recommended.name if recommended else None,
            "recommended_composite": recommended.composite if recommended else None,
            "servings": servings,
            "scaled_to": scaled,
            "hand_ranking": [(c.name, c.composite) for c in cooks[:4]],
            "system_ranking": ranking,
            "cookable_count": len(cooks),
        },
        verdict=verdict,
        passed=passed_system and case_defect is None,
        explanation=reason,
        case_defect=case_defect,
        diagnostics={
            "profile_readback": profile_readback,
            "ranking_first_aligned": ranking_first_aligned,
            "system_ranking_matches_hand": ranking_matches_hand,
            "reason_message": next(
                (m for m in state.get("stream_messages", []) if m.startswith("[reason]")), None
            ),
            "pantry": names,
        },
        reset_verification={
            "tables_after_reset": len(reset),
            "all_empty": all(v == 0 for v in reset.values()),
        },
    )


async def run_dimension5(case_limit: int | None = None) -> DimensionResult:
    cases = PERSONALIZATION_CASES[:case_limit] if case_limit is not None else PERSONALIZATION_CASES
    start = time.monotonic()
    before = file_fingerprints()
    corpus = await load_corpus()
    world = IsolatedWorld()
    results: list[ScenarioCaseResult] = []
    breaker.start(NAME)
    try:
        for case in cases:
            breaker.check()
            results.append(await _run_case(case, world, corpus))
        breaker.check()
    finally:
        breaker.stop()
        await world.cleanup()
    after = file_fingerprints()
    untouched = before == after
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    by_aspect: dict[str, list[int]] = {}
    for case, r in zip(cases, results, strict=True):
        counts = by_aspect.setdefault(case.aspect.kind, [0, 0])
        counts[1] += 1
        counts[0] += int(r.passed)
    tokens = sum(
        int(call.get("total_tokens", 0))
        for call in get_text_provider().get_call_log()
        if str(call.get("trace_id", "")).startswith("eval-d5-")
    )
    score = passed / n if n else 0.0
    return DimensionResult(
        name=NAME,
        pass_threshold=PASS_THRESHOLD,
        score=score,
        passed=n > 0 and score >= PASS_THRESHOLD and untouched,
        metrics={
            "cases_passed": passed,
            "cases_total": n,
            "pass_threshold": PASS_THRESHOLD,
            "by_aspect_passed_of_total": {k: f"{a}/{b}" for k, (a, b) in sorted(by_aspect.items())},
            "verdicts": {
                v: sum(1 for r in results if r.verdict == v) for v in sorted({r.verdict for r in results})
            },
            "misaligned": [r.case_id for r in results if r.verdict == "misaligned"],
            # Passed on outcome, but the system's own ranking did not reflect the signal: the right answer
            # came from tie-breaking or from the language model, not from the scoring.
            "passed_without_scoring_support": [
                r.case_id
                for r in results
                if r.passed and r.diagnostics.get("system_ranking_matches_hand") is False
            ],
            "ranking_matches_hand_count": sum(
                1 for r in results if r.diagnostics.get("system_ranking_matches_hand") is True
            ),
            "ranking_checked_count": sum(
                1 for r in results if r.diagnostics.get("system_ranking_matches_hand") is not None
            ),
            "case_defects": [r.case_id for r in results if r.case_defect],
            "ranking_aligned_but_final_not": [
                r.case_id
                for r in results
                if r.diagnostics.get("ranking_first_aligned") is True and r.verdict == "misaligned"
            ],
            "profile_data_points": {
                r.case_id: r.diagnostics["profile_readback"].get("cuisine_data_points")
                for r in results
                if r.diagnostics["profile_readback"].get("cuisine_data_points")
            },
            "real_data_untouched": untouched,
            "real_db_fingerprints": after,
        },
        case_count=n,
        api_calls=n,
        total_tokens=tokens,
        wall_clock_seconds=time.monotonic() - start,
        scenario_case_results=results,
    )
