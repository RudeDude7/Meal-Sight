"""run_recommendation — the single entry point that binds a trace id,
starts all three MCP servers, runs the compiled graph once, and returns
final state.
"""

from __future__ import annotations

import uuid
from typing import cast

from mealsight.agent.graph import build_graph
from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.state import MealSightState
from mealsight.utils.logging import bind_trace_id, get_logger

logger = get_logger("mealsight.agent.runner")


async def run_recommendation(
    image_bytes: bytes | None = None,
    audio_bytes: bytes | None = None,
    text_input: str | None = None,
) -> MealSightState:
    """Runs one full recommendation end to end.

    Binds a fresh trace id FIRST, before anything else — every log line
    from every node and every MCP call this run makes (mealsight.agent.
    mcp_client.MCPClientManager.call_tool's own logging included) picks
    it up automatically via mealsight.utils.logging's contextvar-based
    propagation, with no need to thread the id through any function
    signature by hand.

    Starts all three MCP servers via MCPClientManager as an async
    context manager, which is what guarantees shutdown happens even if
    graph execution itself raises — __aexit__ runs unconditionally on
    the way out of the `async with` block, exception or not, so a
    failed recommendation never leaves an orphaned subprocess running.
    The graph itself is genuinely stub-only in this phase (see
    mealsight.agent.graph and mealsight.agent.nodes) — no node here
    actually calls into the MCP manager yet — but the manager still
    starts and stops on every real run, exactly as a filled-in graph
    will need it to.
    """
    trace_id = str(uuid.uuid4())
    bind_trace_id(trace_id)
    logger.info("recommendation_started", trace_id=trace_id)

    initial_state: MealSightState = {
        "image_bytes": image_bytes,
        "audio_bytes": audio_bytes,
        "text_input": text_input,
        "trace_id": trace_id,
        "stream_messages": [],
    }

    graph = build_graph()
    async with MCPClientManager():
        final_state = cast(MealSightState, await graph.ainvoke(initial_state))

    logger.info("recommendation_finished", trace_id=trace_id)
    return final_state
