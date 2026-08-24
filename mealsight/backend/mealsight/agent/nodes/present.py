"""present — STUB (mealsight.agent.nodes._common.run_stub).

Will assemble final_response — the actual text/structured summary a
user sees — from top_recommendation, scaled_recipe, nutrition_info,
grocery_list, freshness_alerts, and conflicts_detected, and populate
processing_trace from everything logged along the way (this graph's own
stream_messages, plus every MCPClientManager.call_tool log line for
this run's trace_id). The last node in the graph; nothing runs after
it.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "present"
DESCRIPTION = "Will assemble final_response and processing_trace from everything gathered this run."


async def present(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
