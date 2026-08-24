"""Shared helper every node stub in this package calls — logs entry and
exit and appends one stream message naming what the node will
eventually do, then passes state through unchanged (returning nothing
but the accumulator update).

Filling a node in, in a later session, means replacing the body of that
one node's function with real logic — the file, the function name, and
its registration in mealsight.agent.graph.NODE_ORDER all stay exactly
as they are now, so this phase's own graph shape survives unchanged
into whichever session actually implements node behavior.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.state import MealSightState
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes")


async def run_stub(node_name: str, description: str, state: MealSightState) -> dict[str, Any]:
    logger.info("node_started", node=node_name)
    logger.info("node_finished", node=node_name)
    return {"stream_messages": [f"[{node_name}] {description}"]}
