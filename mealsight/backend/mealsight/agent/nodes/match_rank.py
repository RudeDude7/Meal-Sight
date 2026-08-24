"""match_rank — STUB (mealsight.agent.nodes._common.run_stub).

Will call recipe_engine's match_ingredients (against available_
ingredients, i.e. what's actually verified in the pantry — never an
unverified, off-camera-only mention) for every candidate in recipe_
candidates, and user_intelligence's check_repetition to down-rank
anything cooked too recently — check_repetition's own recommendation
("too_repetitive" etc.) is a signal to weigh here, never a hard veto,
per that tool's own docstring. Writes the ranked, scored result to
matched_recipes.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "match_rank"
DESCRIPTION = (
    "Will score recipe_candidates against available ingredients (match_ingredients) and "
    "recent history (check_repetition) to produce matched_recipes."
)


async def match_rank(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
