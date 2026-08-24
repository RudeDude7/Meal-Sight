"""search_recipes — STUB (mealsight.agent.nodes._common.run_stub).

Will call the recipe_engine server's own search_recipes tool, filtered
by unified_request's dietary_restrictions/cuisine_preference/max_cook_
time_minutes, writing the resulting summaries to recipe_candidates —
compact results only (recipe_engine's own search_recipes never returns
full ingredients/steps, by design), just enough candidates for match_
rank to actually score.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "search_recipes"
DESCRIPTION = (
    "Will call recipe_engine's search_recipes, filtered by the unified request's "
    "hard constraints, to build recipe_candidates."
)


async def search_recipes(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
