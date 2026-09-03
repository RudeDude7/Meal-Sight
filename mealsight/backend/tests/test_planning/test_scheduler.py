"""Tests for mealsight.planning.scheduler.build_schedule — pure,
deterministic, no database or MCP server involved anywhere in this
file, which is exactly what mealsight.planning is designed to allow."""

from __future__ import annotations

import pytest

from mealsight.planning.models import PlanCandidate, PlanConstraintsUnsatisfiable
from mealsight.planning.scheduler import build_schedule


def _candidate(
    recipe_id: str,
    *,
    name: str | None = None,
    cuisine: str | None = "italian",
    protein_type: str | None = None,
    match_score: float = 0.8,
    can_cook: bool = True,
    critical_missing: list[str] | None = None,
    missing_ingredient_names: list[str] | None = None,
    uses_expiring_ingredient_names: list[str] | None = None,
    cuisine_score: float = 0.5,
    repetition_score: float = 0.0,
) -> PlanCandidate:
    return PlanCandidate(
        recipe_id=recipe_id,
        name=name or recipe_id,
        cuisine=cuisine,
        meal_type="main",
        cook_time_minutes=30,
        match_score=match_score,
        can_cook=can_cook,
        critical_missing=critical_missing or [],
        missing_ingredient_names=missing_ingredient_names or [],
        all_ingredient_names=[],
        protein_type=protein_type,
        uses_expiring_ingredient_names=uses_expiring_ingredient_names or [],
        cuisine_score=cuisine_score,
        repetition_score=repetition_score,
        repetition_recommendation=None,
    )


# --------------------------------------------------------------------
# cuisine variety
# --------------------------------------------------------------------


def test_no_cuisine_repeats_on_consecutive_days_when_alternatives_exist() -> None:
    candidates = [
        _candidate("r1", cuisine="italian"),
        _candidate("r2", cuisine="italian"),
        _candidate("r3", cuisine="mexican"),
        _candidate("r4", cuisine="mexican"),
        _candidate("r5", cuisine="thai"),
    ]
    result = build_schedule(candidates, days=5, max_same_protein_per_week=99)

    cuisines = [day.cuisine for day in result.days]
    for i in range(len(cuisines) - 1):
        assert cuisines[i] != cuisines[i + 1], f"day {i} and {i + 1} both {cuisines[i]}"
    assert not any(day.cuisine_repeat_forced for day in result.days)


def test_cuisine_repeat_is_forced_and_flagged_when_no_alternative_exists() -> None:
    # Only one cuisine available at all — the softer variety goal must
    # relax rather than the whole plan failing over it.
    candidates = [_candidate(f"r{i}", cuisine="italian") for i in range(5)]
    result = build_schedule(candidates, days=5, max_same_protein_per_week=99)

    assert len(result.days) == 5
    assert result.days[0].cuisine_repeat_forced is False  # nothing to repeat yet on day 1
    assert all(day.cuisine_repeat_forced for day in result.days[1:])


# --------------------------------------------------------------------
# protein variety
# --------------------------------------------------------------------


def test_protein_variety_respects_the_configured_maximum() -> None:
    # 5 chicken candidates (cap=2 will bind), plus 5 candidates each
    # carrying its OWN distinct protein type — those never compete with
    # each other for the cap, so 5 days is genuinely fillable: at most
    # 2 chicken days, the rest from the five distinct single-use
    # proteins.
    other_proteins = ["beans", "tofu", "salmon", "egg", "lentils"]
    candidates = [
        _candidate(f"chicken-{i}", cuisine=f"cuisine{i}", protein_type="chicken") for i in range(5)
    ] + [
        _candidate(f"other-{protein}", cuisine=f"other-cuisine-{protein}", protein_type=protein)
        for protein in other_proteins
    ]

    result = build_schedule(candidates, days=5, max_same_protein_per_week=2)

    protein_counts: dict[str, int] = {}
    for day in result.days:
        if day.protein_type:
            protein_counts[day.protein_type] = protein_counts.get(day.protein_type, 0) + 1
    assert protein_counts.get("chicken", 0) <= 2


def test_a_recipe_with_no_protein_type_never_counts_against_the_cap() -> None:
    candidates = [_candidate(f"veg-{i}", cuisine=f"c{i}", protein_type=None) for i in range(5)]
    result = build_schedule(candidates, days=5, max_same_protein_per_week=1)
    assert len(result.days) == 5


# --------------------------------------------------------------------
# expiring ingredients land early
# --------------------------------------------------------------------


def test_expiring_ingredient_lands_on_an_early_day_not_the_last() -> None:
    # One candidate uses an expiring ingredient; several equally-good
    # non-expiring candidates fill out the rest of the week. The
    # day-position-decayed freshness bonus should make the expiring
    # candidate win an EARLY day, not get pushed to day 5 just because
    # nothing forces an order otherwise.
    candidates = [
        _candidate(
            "expiring-spinach",
            cuisine="c0",
            match_score=0.5,
            uses_expiring_ingredient_names=["spinach"],
        )
    ] + [_candidate(f"plain-{i}", cuisine=f"c{i + 1}", match_score=0.5) for i in range(4)]

    result = build_schedule(candidates, days=5, max_same_protein_per_week=99)

    expiring_day = next(day.day_index for day in result.days if day.recipe_id == "expiring-spinach")
    assert expiring_day == 0


def test_expiring_ingredient_no_longer_flagged_once_used() -> None:
    candidates = [
        _candidate("uses-spinach", cuisine="c0", uses_expiring_ingredient_names=["spinach"]),
    ] + [_candidate(f"plain-{i}", cuisine=f"c{i + 1}") for i in range(4)]

    result = build_schedule(candidates, days=5, max_same_protein_per_week=99)
    used_day = next(day for day in result.days if day.recipe_id == "uses-spinach")
    assert used_day.uses_expiring_ingredient_names == ["spinach"]
    # No other day should still list spinach as expiring-and-usable —
    # it's already been used once.
    for day in result.days:
        if day.recipe_id != "uses-spinach":
            assert "spinach" not in day.uses_expiring_ingredient_names


# --------------------------------------------------------------------
# cross-day overlap reduces total distinct ingredients
# --------------------------------------------------------------------


def test_overlap_optimization_uses_fewer_distinct_ingredients_than_disabled() -> None:
    # miso-soup is the clear day-1 winner either way (highest match_score,
    # so this isn't testing day 1 at all). Day 2 is where the two modes
    # diverge: miso-glazed needs ONLY the same "miso" day 1 already
    # commits to buying (a genuine zero-marginal-cost pick once overlap
    # scoring can see that), while filler-b needs a brand-new ingredient
    # nothing else in the plan touches. filler-b's own raw match_score is
    # deliberately higher than miso-glazed's, so filler-b wins on
    # match_score alone whenever overlap scoring is off — the overlap
    # bonus is what has to close that gap for miso-glazed to win instead.
    candidates = [
        _candidate("miso-soup", cuisine="japanese", match_score=0.90, missing_ingredient_names=["miso"]),
        _candidate(
            "miso-glazed", cuisine="korean", match_score=0.50, missing_ingredient_names=["miso"]
        ),
        _candidate("filler-a", cuisine="mexican", match_score=0.65, missing_ingredient_names=["chorizo"]),
        _candidate("filler-b", cuisine="thai", match_score=0.68, missing_ingredient_names=["fish sauce"]),
    ]

    with_overlap = build_schedule(
        list(candidates), days=2, max_same_protein_per_week=99, enable_overlap_bonus=True
    )
    without_overlap = build_schedule(
        list(candidates), days=2, max_same_protein_per_week=99, enable_overlap_bonus=False
    )

    def distinct_count(days: list) -> int:  # type: ignore[type-arg]
        names: set[str] = set()
        for day in days:
            names.update(day.missing_ingredient_names)
        return len(names)

    with_count = distinct_count(with_overlap.days)
    without_count = distinct_count(without_overlap.days)
    assert with_count < without_count, (with_count, without_count)
    assert {d.recipe_id for d in with_overlap.days} == {"miso-soup", "miso-glazed"}
    assert {d.recipe_id for d in without_overlap.days} == {"miso-soup", "filler-b"}


# --------------------------------------------------------------------
# impossible constraints fail honestly
# --------------------------------------------------------------------


def test_impossible_constraints_raise_rather_than_producing_a_partial_plan() -> None:
    # Only 3 distinct candidates, no exact repeats allowed, 5 days
    # requested — genuinely impossible to fill honestly.
    candidates = [_candidate(f"r{i}", cuisine=f"c{i}") for i in range(3)]

    with pytest.raises(PlanConstraintsUnsatisfiable) as exc_info:
        build_schedule(candidates, days=5, max_same_protein_per_week=99)

    assert exc_info.value.day_index == 3  # the 4th day (0-indexed) is the one that ran dry


def test_impossible_protein_cap_raises_rather_than_silently_ignoring_it() -> None:
    candidates = [_candidate(f"chicken-{i}", cuisine=f"c{i}", protein_type="chicken") for i in range(5)]

    with pytest.raises(PlanConstraintsUnsatisfiable):
        build_schedule(candidates, days=5, max_same_protein_per_week=1)


# --------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------


def test_schedule_is_deterministic_across_repeated_runs() -> None:
    candidates = [_candidate(f"r{i}", cuisine=f"c{i % 3}", match_score=0.5 + i * 0.01) for i in range(10)]
    first = build_schedule(list(candidates), days=5, max_same_protein_per_week=99)
    second = build_schedule(list(candidates), days=5, max_same_protein_per_week=99)
    assert [d.recipe_id for d in first.days] == [d.recipe_id for d in second.days]


def test_no_exact_recipe_is_repeated_within_a_plan() -> None:
    candidates = [_candidate(f"r{i}", cuisine=f"c{i}") for i in range(5)]
    result = build_schedule(candidates, days=5, max_same_protein_per_week=99)
    assert len({d.recipe_id for d in result.days}) == 5


def test_critical_missing_is_penalized_not_excluded() -> None:
    candidates = [
        _candidate("has-gap", cuisine="c0", match_score=0.9, critical_missing=["saffron"]),
        _candidate("clean", cuisine="c1", match_score=0.5),
    ]
    result = build_schedule(candidates, days=1, max_same_protein_per_week=99)
    # The clean, lower-raw-score candidate should win day 1 despite a
    # lower match_score, since a critical gap outweighs everything else
    # — matching agent/nodes/match_rank.py's own established precedent.
    assert result.days[0].recipe_id == "clean"
