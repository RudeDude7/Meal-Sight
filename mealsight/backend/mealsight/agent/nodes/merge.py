"""merge — STUB (mealsight.agent.nodes._common.run_stub).

Will call mealsight.perception.fusion.merge_perceptions on whichever of
vision_result/audio_result/text_result actually got set by perceive,
passing the user_profile once get_context has fetched one, and write
the result to unified_request. merge_perceptions itself raises
ValueError when literally nothing was perceived at all — this node's
real job is deciding what the graph does with THAT case (an error
node? an early exit to present with an explanatory message?), not
something a stub needs to resolve yet.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "merge"
DESCRIPTION = "Will call merge_perceptions to combine vision/audio/text into one UnifiedMealRequest."


async def merge(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
