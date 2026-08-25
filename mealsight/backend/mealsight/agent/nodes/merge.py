"""merge — fetches the user profile via the user_intelligence MCP
server FIRST, then calls mealsight.perception.fusion.merge_perceptions
with it.

Profile-first, not the other way around, because merge_perceptions is
deliberately DB-free (phase 5.3) and takes user_profile as an optional
argument specifically so its own module never has to reach a database
or an MCP server itself — something upstream has to have already
fetched it. This node is that something. The fetched profile is also
written to state["user_profile"] here, once, so get_context (node 5)
can reuse it rather than calling get_user_profile a second time.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.perception.fusion import merge_perceptions
from mealsight.user_intelligence.models import UserProfile
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.merge")

NODE_NAME = "merge"


def _conflict_message(conflict: Any) -> str:
    field_label = conflict.field.replace("_", " ")
    return (
        f"[{NODE_NAME}] Heads up — {field_label}: you said {conflict.audio_value!r} out loud but "
        f"typed {conflict.text_value!r}; went with {conflict.chosen_value!r}."
    )


async def _fetch_user_profile(
    runtime: Runtime[AgentContext],
) -> tuple[UserProfile | None, dict[str, Any] | None]:
    result = await runtime.context.mcp.call_tool("user_intelligence", "get_user_profile", {})
    if not result.success or not isinstance(result.data, dict):
        logger.warning("merge_profile_fetch_failed", error=result.error)
        return None, None
    try:
        return UserProfile.model_validate(result.data), result.data
    except Exception:
        logger.error("merge_profile_parse_failed", exc_info=True)
        return None, result.data


async def merge(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input to merge."]}

    vision = state.get("vision_result")
    audio = state.get("audio_result")
    text = state.get("text_result")

    if vision is None and audio is None and text is None:
        logger.warning("node_finished", node=NODE_NAME, reason="nothing to merge")
        return {"stream_messages": [f"[{NODE_NAME}] Nothing usable came out of perception to merge."]}

    user_profile, raw_profile = await _fetch_user_profile(runtime)

    try:
        unified = merge_perceptions(vision, audio, text, user_profile=user_profile)
    except Exception:
        logger.error("merge_unexpected_failure", exc_info=True)
        return {"stream_messages": [f"[{NODE_NAME}] Failed to combine your inputs unexpectedly."]}

    messages = [
        f"[{NODE_NAME}] Combined your {', '.join(unified.modalities_received)} input into one request."
    ]
    messages.extend(_conflict_message(conflict) for conflict in unified.conflicts_detected)

    update: dict[str, Any] = {"unified_request": unified, "stream_messages": messages}
    if raw_profile is not None:
        update["user_profile"] = raw_profile

    logger.info("node_finished", node=NODE_NAME, conflicts=len(unified.conflicts_detected))
    return update
