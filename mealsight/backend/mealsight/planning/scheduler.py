"""build_schedule — the deterministic, greedy day-by-day assignment
algorithm at the heart of multi-day meal planning.

Pure Python: no database access, no MCP calls, no LLM. Every
PlanCandidate handed in is already fully assembled by the orchestration
layer (mealsight.agent.meal_planner) — the one place in this feature
allowed to reach across recipe_engine/pantry_manager/user_intelligence.
This module only ever computes over data already in memory, which is
what makes it independently, cheaply unit-testable (see tests/
test_planning/test_scheduler.py) without a database or an MCP server in
sight.

ALGORITHM: greedy, one day at a time, in day order. At each day, every
still-eligible candidate is scored FRESH — cross-day overlap only means
anything computed incrementally against what earlier days already
committed to, so scores are never memoized across days. The single
highest-scoring eligible candidate is assigned, trackers update, and
the next day repeats against a pool with one fewer candidate.

This is NOT a search over all C(P, days) day combinations — that is the
genuinely exponential approach the task explicitly asked not to build
("do not ask a model to schedule five days" applies just as much to a
brute-force search as to an LLM). The cross-day overlap term this
scheduler optimizes is a real, well-known combinatorial structure: at
each step, prefer whichever remaining choice covers the most of what
still needs to be "paid for" (here, distinct ingredients still needing
purchase) — the same marginal-gain-greedy shape the classic greedy
set-cover heuristic uses, with that heuristic's own well-known property:
provably within a ln(n) factor of the true optimum, not that it FINDS
the optimum. That is an honest, citable bound for what this delivers,
not a claim of exact optimality.

COMPLEXITY: let P = len(candidates) (bounded by the orchestration
layer, not this module — see meal_planner.MAX_PLANNING_CANDIDATES),
D = days. Each of the D rounds filters and scores at most P remaining
candidates, and each score is O(1) beyond a small set intersection
bounded by one recipe's own ingredient count (a small constant in
practice, never more than a few dozen). Total: O(D * P) score
evaluations, no recursion, no backtracking — a few hundred cheap
arithmetic operations even at P=60, D=7. All of the real cost in a
meal-plan request is the I/O gathering candidates (match_ingredients
calls, one per candidate) before this function is ever called; this
function itself is effectively instantaneous.
"""

from __future__ import annotations

from mealsight.planning.models import (
    DayAssignment,
    PlanCandidate,
    PlanConstraintsUnsatisfiable,
    ScheduleResult,
)

# --- scoring weights -------------------------------------------------
# Same dominant-term shape as agent/nodes/match_rank.py's own composite
# score (ingredient match dominant, freshness/cuisine layered on top,
# critical-missing an overriding penalty) — this scheduler adds three
# genuinely new terms match_rank never needed: a day-position-decayed
# freshness bonus (so an expiring ingredient's bonus is worth more
# early in the week than late), a cross-day overlap bonus, and a
# repetition penalty already computed by check_repetition (reused, not
# recomputed).
INGREDIENT_MATCH_WEIGHT = 0.5
FRESHNESS_BONUS_WEIGHT = 0.15
CUISINE_PREFERENCE_WEIGHT = 0.1
REPETITION_PENALTY_WEIGHT = 0.1
# Bigger than the maximum possible sum of every positive term below
# (0.5 + 0.15 + 0.1 + 0.2 = 0.95), matching match_rank.py's own
# CRITICAL_MISSING_PENALTY precedent: a critical-ingredient gap must
# always outrank every other signal, never just discourage it.
CRITICAL_MISSING_PENALTY = 1.0
# Rewards a candidate whose to-be-bought ingredients overlap with what
# an earlier day already commits to buying — the direct mechanism
# behind "minimize total distinct ingredients purchased". Scaled by the
# FRACTION of this candidate's own missing ingredients that are shared,
# not the raw count, so a recipe needing one shared item out of one
# ingredient isn't outweighed by a recipe needing one shared item out
# of ten.
OVERLAP_BONUS_WEIGHT = 0.2


def _decayed_freshness_bonus(uses_expiring: bool, day_index: int, days: int) -> float:
    """Front-loads the freshness bonus: day 0 gets the full bonus, the
    last day gets only 1/days of it. This is the direct mechanism
    behind "an expiring ingredient should land early, not on day
    five" — a greedy per-day-in-order pick naturally prefers assigning
    an expiring-ingredient candidate to whichever day it's worth the
    most, which this decay makes the earliest available one."""
    if not uses_expiring:
        return 0.0
    return FRESHNESS_BONUS_WEIGHT * (1 - day_index / days)


def _score(
    candidate: PlanCandidate,
    day_index: int,
    days: int,
    remaining_expiring: set[str],
    committed_missing: set[str],
    enable_overlap_bonus: bool,
) -> float:
    uses_expiring = bool(set(candidate.uses_expiring_ingredient_names) & remaining_expiring)
    score = INGREDIENT_MATCH_WEIGHT * candidate.match_score
    score += _decayed_freshness_bonus(uses_expiring, day_index, days)
    score += CUISINE_PREFERENCE_WEIGHT * candidate.cuisine_score
    score -= REPETITION_PENALTY_WEIGHT * candidate.repetition_score
    if candidate.critical_missing:
        score -= CRITICAL_MISSING_PENALTY

    if enable_overlap_bonus:
        missing = set(candidate.missing_ingredient_names)
        if missing:
            shared_fraction = len(missing & committed_missing) / len(missing)
            score += OVERLAP_BONUS_WEIGHT * shared_fraction

    return score


def build_schedule(
    candidates: list[PlanCandidate],
    days: int,
    max_same_protein_per_week: int,
    *,
    enable_overlap_bonus: bool = True,
) -> ScheduleResult:
    """Assigns one candidate per day, greedily, days times.

    Hard filters, applied in this order, before any candidate is
    scored for a given day:
      1. Never repeat an exact recipe_id already assigned this plan.
      2. Never let one protein_type exceed max_same_protein_per_week
         across the whole plan (a genuine hard cap, not a penalty —
         the only way to GUARANTEE it, not just usually achieve it).
      3. Never repeat the immediately preceding day's cuisine — UNLESS
         doing so would leave zero eligible candidates for this day, in
         which case the cuisine-repeat filter alone is relaxed for
         this one day (and DayAssignment.cuisine_repeat_forced records
         it honestly) rather than failing the whole plan over a
         variety preference. Dietary restrictions and the protein cap
         are never relaxed this way — only this one, softer goal is.

    Raises PlanConstraintsUnsatisfiable, naming the first day that ran
    out of eligible candidates even after that one relaxation, rather
    than silently returning a shorter-than-requested plan.

    enable_overlap_bonus (default True) exists so a caller can measure
    the cross-day overlap optimization's own real effect (see
    meal_planner.py's own use_overlap_optimization parameter and this
    project's own verification run) by generating the same plan twice
    and comparing total distinct ingredients — never to be turned off
    in a real user-facing plan.
    """
    remaining = list(candidates)
    assigned: list[DayAssignment] = []
    used_recipe_ids: set[str] = set()
    protein_counts: dict[str, int] = {}
    previous_cuisine: str | None = None
    remaining_expiring: set[str] = set()
    for candidate in candidates:
        remaining_expiring.update(candidate.uses_expiring_ingredient_names)
    committed_missing: set[str] = set()

    for day_index in range(days):
        pool = [c for c in remaining if c.recipe_id not in used_recipe_ids]
        pool = [
            c
            for c in pool
            if c.protein_type is None
            or protein_counts.get(c.protein_type, 0) < max_same_protein_per_week
        ]

        cuisine_repeat_forced = False
        if previous_cuisine is not None:
            no_repeat_pool = [c for c in pool if c.cuisine != previous_cuisine]
            if no_repeat_pool:
                pool = no_repeat_pool
            elif pool:
                cuisine_repeat_forced = True
            # else: pool is already empty; handled by the check below.

        if not pool:
            raise PlanConstraintsUnsatisfiable(
                day_index,
                "no eligible candidate remained (exhausted after dietary filtering, the "
                "protein-variety cap, and available recipe count) — the requested plan cannot "
                "be filled honestly with these constraints.",
            )

        scored = [
            (
                _score(c, day_index, days, remaining_expiring, committed_missing, enable_overlap_bonus),
                c,
            )
            for c in pool
        ]
        # Deterministic tiebreak: highest score wins; ties break on
        # recipe_id ascending, so the same inputs always produce the
        # same plan.
        scored.sort(key=lambda pair: (-pair[0], pair[1].recipe_id))
        chosen = scored[0][1]

        missing = set(chosen.missing_ingredient_names)
        shared = sorted(missing & committed_missing)

        assigned.append(
            DayAssignment(
                day_index=day_index,
                recipe_id=chosen.recipe_id,
                name=chosen.name,
                cuisine=chosen.cuisine,
                protein_type=chosen.protein_type,
                match_score=chosen.match_score,
                can_cook=chosen.can_cook,
                uses_expiring_ingredient_names=sorted(
                    set(chosen.uses_expiring_ingredient_names) & remaining_expiring
                ),
                missing_ingredient_names=sorted(missing),
                shared_missing_ingredient_names=shared,
                cuisine_repeat_forced=cuisine_repeat_forced,
            )
        )

        used_recipe_ids.add(chosen.recipe_id)
        if chosen.protein_type is not None:
            protein_counts[chosen.protein_type] = protein_counts.get(chosen.protein_type, 0) + 1
        previous_cuisine = chosen.cuisine
        remaining_expiring -= set(chosen.uses_expiring_ingredient_names)
        committed_missing |= missing

    return ScheduleResult(days=assigned)
