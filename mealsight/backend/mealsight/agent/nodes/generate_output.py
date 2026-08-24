"""generate_output — STUB (mealsight.agent.nodes._common.run_stub).

Will build the concrete, actionable artifacts around top_recommendation:
recipe_engine's scale_recipe (-> scaled_recipe, sized to unified_
request.servings) and calculate_nutrition (-> nutrition_info), and —
when there's anything genuinely missing after match_rank's own
ingredient match — pantry_manager's create_grocery_list (-> grocery_
list). Not every run necessarily needs a grocery list; this node's real
job includes deciding when one is actually warranted, not just always
calling all three tools.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "generate_output"
DESCRIPTION = (
    "Will build scaled_recipe, nutrition_info, and (when needed) grocery_list for "
    "top_recommendation."
)


async def generate_output(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
