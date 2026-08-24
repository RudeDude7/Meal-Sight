"""reason — STUB (mealsight.agent.nodes._common.run_stub).

Will use an LLM (mealsight.providers.get_text_provider) to pick one
top_recommendation from matched_recipes and justify it against
everything gathered so far — freshness_alerts, conflicts_detected,
mood_or_preference, cuisine_preferences — the one node in this graph
whose own output is genuinely non-deterministic (temperature=0.0
notwithstanding, this is a real judgment call over ranked candidates,
not a deterministic filter/sort the way match_rank's own scoring is).
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "reason"
DESCRIPTION = "Will use an LLM to select and justify one top_recommendation from matched_recipes."


async def reason(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
