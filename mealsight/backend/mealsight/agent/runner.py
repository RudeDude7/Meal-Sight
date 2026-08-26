"""run_recommendation — the single entry point that binds a trace id,
starts all three MCP servers, runs the compiled graph once, and returns
final state.
"""

from __future__ import annotations

import uuid
from typing import cast

from mealsight.agent.context import AgentContext, StreamSink
from mealsight.agent.graph import build_graph
from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.state import MealSightState
from mealsight.utils.logging import bind_trace_id, get_logger

logger = get_logger("mealsight.agent.runner")


async def run_recommendation(
    image_bytes: bytes | None = None,
    audio_bytes: bytes | None = None,
    text_input: str | None = None,
    *,
    manager: MCPClientManager | None = None,
    trace_id: str | None = None,
    stream: StreamSink | None = None,
) -> MealSightState:
    """Runs one full recommendation end to end.

    trace_id: supply this when a caller already has an id this run
    needs to be correlated with (mealsight.api's own recommend router
    passes its session_id here, so the exact id returned to a client in
    the 202 response is the same one that shows up in every log line
    for this run — never generated independently of what the caller
    already handed back). Omitted, a fresh one is generated exactly as
    before this parameter existed.

    stream: an optional mealsight.agent.context.StreamSink (mealsight.
    api's own SessionStream, concretely) forwarded straight into
    AgentContext — every node checks runtime.context.stream for None
    before emitting anything, so omitting this (every script, every
    test, unchanged) means every node's own progress-emitting code path
    is simply never reached, not that it errors.

    Binds the trace id FIRST, before anything else — every log line
    from every node and every MCP call this run makes (mealsight.agent.
    mcp_client.MCPClientManager.call_tool's own logging included) picks
    it up automatically via mealsight.utils.logging's contextvar-based
    propagation, with no need to thread the id through any function
    signature by hand.

    manager: an already-started MCPClientManager to reuse (mealsight.api
    holds one for the whole process lifetime in its own lifespan,
    starting all three MCP subprocesses ONCE instead of per request —
    ~13s of a real ~19.4s run was pure subprocess-startup-and-health-
    check cost before that existed). When omitted (every script and
    test that calls this directly, unchanged from before this phase),
    this function starts and tears down its own manager exactly as it
    always has, via `async with MCPClientManager()` — __aexit__ runs
    unconditionally on the way out of that block, exception or not, so
    a failed standalone recommendation still never leaks a subprocess.
    A caller-supplied manager is never started or shut down here; it's
    the caller's own responsibility both ways, since its lifetime is by
    definition longer than one recommendation.
    """
    trace_id = trace_id or str(uuid.uuid4())
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

    if manager is not None:
        final_state = cast(
            MealSightState,
            await graph.ainvoke(initial_state, context=AgentContext(mcp=manager, stream=stream)),
        )
    else:
        async with MCPClientManager() as owned_manager:
            final_state = cast(
                MealSightState,
                await graph.ainvoke(
                    initial_state, context=AgentContext(mcp=owned_manager, stream=stream)
                ),
            )

    logger.info("recommendation_finished", trace_id=trace_id)
    return final_state
