"""get_context — fetches situational context signals and recent meal
history from the user_intelligence MCP server, in the same MCP
session everything else this run uses.

Deliberately does NOT call get_user_profile: merge (node 3) already
fetched it and wrote it to state["user_profile"] specifically so this
node doesn't have to — see merge.py's own docstring for why profile
fetching happens there instead of here.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.get_context")

NODE_NAME = "get_context"


async def get_context(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    logger.info(
        "get_context_profile_reused", node=NODE_NAME, has_profile=state.get("user_profile") is not None
    )

    signals_result, history_result = await asyncio.gather(
        runtime.context.mcp.call_tool("user_intelligence", "get_context_signals", {}),
        runtime.context.mcp.call_tool("user_intelligence", "get_meal_history", {}),
    )

    update: dict[str, Any] = {}
    messages: list[str] = []

    if signals_result.success and isinstance(signals_result.data, dict):
        update["context_signals"] = signals_result.data
        meal_type = signals_result.data.get("meal_type", "a meal")
        suggestion = signals_result.data.get("complexity_suggestion", "")
        messages.append(f"[{NODE_NAME}] Looks like it's {meal_type} time. {suggestion}".strip())
    else:
        messages.append(
            f"[{NODE_NAME}] Couldn't get context signals: {signals_result.error or 'unknown error'}."
        )

    if history_result.success and isinstance(history_result.data, dict):
        meals = history_result.data.get("meals", [])
        update["meal_history"] = meals
        messages.append(f"[{NODE_NAME}] Found {len(meals)} recent meal(s) in your history.")
    else:
        messages.append(
            f"[{NODE_NAME}] Couldn't get meal history: {history_result.error or 'unknown error'}."
        )

    update["stream_messages"] = messages
    logger.info("node_finished", node=NODE_NAME)
    return update
