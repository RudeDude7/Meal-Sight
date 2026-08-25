"""update_pantry — writes vision-identified items to the real pantry
via the pantry_manager MCP server, then checks what's expiring soon —
regardless of whether THIS run's photo produced anything new, since
the pantry from prior runs still exists and still matters. Skips the
write when there's nothing to write (no photo, or a photo with nothing
identified) but never skips the expiring-items check.

Also reads the pantry back via get_pantry, after the write, into
state["pantry_items"] — the accumulated, persisted inventory (every
prior run's photo included, not just this run's). match_rank (node 7)
needs this: matching only against this run's own vision-verified items
made anything seen in an earlier photo invisible to ranking, even
though it's still physically in the fridge.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.perception.processor import to_pantry_item_inputs
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.update_pantry")

NODE_NAME = "update_pantry"


async def _apply_pantry_update(state: MealSightState, runtime: Runtime[AgentContext]) -> list[str]:
    vision = state.get("vision_result")
    if vision is None or not vision.identified_items:
        return [f"[{NODE_NAME}] No new items from a photo this run — checking the existing pantry."]

    pantry_items = to_pantry_item_inputs(vision)
    result = await runtime.context.mcp.call_tool(
        "pantry_manager",
        "update_pantry",
        {"items": [item.model_dump(mode="json") for item in pantry_items]},
    )
    if not (result.success and isinstance(result.data, dict)):
        return [f"[{NODE_NAME}] Couldn't update the pantry: {result.error or 'unknown error'}."]

    data = result.data
    messages = [
        f"[{NODE_NAME}] Pantry updated: {data.get('added_count', 0)} new item(s), "
        f"{data.get('updated_count', 0)} quantity update(s)."
    ]
    flagged = data.get("flagged_items") or []
    if flagged:
        names = ", ".join(item.get("name", "?") for item in flagged)
        messages.append(f"[{NODE_NAME}] {len(flagged)} pantry item(s) haven't been seen in a while: {names}.")
    return messages


async def _check_expiring(runtime: Runtime[AgentContext]) -> tuple[list[dict[str, Any]], list[str]]:
    result = await runtime.context.mcp.call_tool("pantry_manager", "flag_expiring", {})
    if not (result.success and isinstance(result.data, dict)):
        return [], [f"[{NODE_NAME}] Couldn't check expiring items: {result.error or 'unknown error'}."]

    items = result.data.get("items", [])
    if not items:
        return items, [f"[{NODE_NAME}] Nothing expiring soon."]

    names = ", ".join(item.get("name", "?") for item in items)
    return items, [f"[{NODE_NAME}] {len(items)} item(s) expiring soon: {names}."]


async def _fetch_pantry_items(runtime: Runtime[AgentContext]) -> tuple[list[dict[str, Any]], list[str]]:
    result = await runtime.context.mcp.call_tool("pantry_manager", "get_pantry", {})
    if not (result.success and isinstance(result.data, dict)):
        return [], [f"[{NODE_NAME}] Couldn't read back the pantry: {result.error or 'unknown error'}."]

    items = result.data.get("items", [])
    return items, [f"[{NODE_NAME}] Pantry now has {len(items)} item(s) on record."]


async def update_pantry(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    try:
        update_messages = await _apply_pantry_update(state, runtime)
    except Exception:
        logger.error("update_pantry_write_unexpected_failure", exc_info=True)
        update_messages = [f"[{NODE_NAME}] Pantry update failed unexpectedly."]

    try:
        expiring_items, expiring_messages = await _check_expiring(runtime)
    except Exception:
        logger.error("update_pantry_expiring_unexpected_failure", exc_info=True)
        expiring_items, expiring_messages = [], [f"[{NODE_NAME}] Expiring-item check failed unexpectedly."]

    try:
        pantry_items, pantry_messages = await _fetch_pantry_items(runtime)
    except Exception:
        logger.error("update_pantry_read_back_unexpected_failure", exc_info=True)
        pantry_items, pantry_messages = [], [f"[{NODE_NAME}] Reading back the pantry failed unexpectedly."]

    logger.info("node_finished", node=NODE_NAME)
    return {
        "expiring_items": expiring_items,
        "pantry_items": pantry_items,
        "stream_messages": [*update_messages, *expiring_messages, *pantry_messages],
    }
