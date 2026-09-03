"""Typed shapes for multi-day meal planning."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlanCandidate(BaseModel):
    """One recipe candidate the scheduler can assign to a day —
    fully assembled by the orchestration layer (mealsight.agent.
    meal_planner) via existing recipe_engine/pantry_manager/
    user_intelligence tools before build_schedule ever sees it. The
    scheduler itself never fetches anything; this is its entire input
    shape, one entry per candidate."""

    model_config = ConfigDict(frozen=True)

    recipe_id: str
    name: str
    cuisine: str | None
    meal_type: str | None
    cook_time_minutes: int | None
    match_score: float
    can_cook: bool
    critical_missing: list[str]
    # What would actually need to be BOUGHT — recipe_engine's own
    # missing_items (post-substitution). This is the set overlap
    # scoring optimizes over, since overlap on something already in the
    # pantry saves nothing at the register.
    missing_ingredient_names: list[str]
    # matched + missing + partial — the recipe's full ingredient set,
    # used only to derive protein_type (see meal_planner.py).
    all_ingredient_names: list[str]
    protein_type: str | None
    # Which currently-expiring pantry items this recipe would use up.
    uses_expiring_ingredient_names: list[str]
    cuisine_score: float
    repetition_score: float
    repetition_recommendation: str | None


class DayAssignment(BaseModel):
    """One day of a built schedule — build_schedule's own output shape,
    before the orchestration layer enriches it with scaled servings,
    grocery detail, and nutrition (see meal_planner.py's own
    MealPlanDay, the public, API-facing shape)."""

    model_config = ConfigDict(frozen=True)

    day_index: int
    recipe_id: str
    name: str
    cuisine: str | None
    protein_type: str | None
    match_score: float
    can_cook: bool
    uses_expiring_ingredient_names: list[str]
    missing_ingredient_names: list[str]
    # missing_ingredient_names this day shares with at least one EARLIER
    # day in the same plan — the direct, reportable evidence the
    # cross-day overlap optimization actually did something.
    shared_missing_ingredient_names: list[str]
    cuisine_repeat_forced: bool


class ScheduleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    days: list[DayAssignment]


class PlanConstraintsUnsatisfiable(Exception):
    """Raised by build_schedule when there is no honest way to fill
    every requested day from the candidates it was given — never
    silently returned as a partial plan. Names which day (0-based)
    first ran out of eligible candidates and why."""

    def __init__(self, day_index: int, reason: str) -> None:
        super().__init__(f"Day {day_index + 1}: {reason}")
        self.day_index = day_index
        self.reason = reason
