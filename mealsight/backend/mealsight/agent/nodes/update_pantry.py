"""update_pantry — STUB (mealsight.agent.nodes._common.run_stub).

Will convert vision_result into pantry_manager-ready input via
mealsight.perception.processor.to_pantry_item_inputs and call the
pantry_manager server's own update_pantry tool through mealsight.agent.
mcp_client.MCPClientManager.call_tool — the real write that makes a
photo's contents actually persist, not just something this run's
UnifiedMealRequest saw once. A run with no vision_result at all (audio/
text only) has nothing to write here and this node becomes a no-op,
which is exactly why vision_result stays optional on MealSightState.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "update_pantry"
DESCRIPTION = "Will write vision-identified items to the pantry via the pantry_manager MCP server."


async def update_pantry(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
