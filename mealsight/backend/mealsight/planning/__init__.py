"""Multi-day meal planning's pure, deterministic core: build_schedule
(scheduler.py) and its typed input/output shapes (models.py). No
database access, no MCP calls, no LLM — see scheduler.py's own module
docstring. The orchestration layer that gathers real data and calls
this module lives in mealsight.agent.meal_planner, deliberately kept
separate: this package must never import anything from mealsight.db,
mealsight.agent, or any MCP server module.
"""

from mealsight.planning.models import (
    DayAssignment,
    PlanCandidate,
    PlanConstraintsUnsatisfiable,
    ScheduleResult,
)
from mealsight.planning.scheduler import build_schedule

__all__ = [
    "DayAssignment",
    "PlanCandidate",
    "PlanConstraintsUnsatisfiable",
    "ScheduleResult",
    "build_schedule",
]
