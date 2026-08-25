"""present — the last node in the graph. Assembles processing_trace —
the debugging record and the raw material for the frontend's own
reasoning display — from everything gathered this run, and streams one
final completion message. final_response itself was already built by
generate_output (node 9); this node doesn't rebuild it, just leaves it
untouched in state.

processing_trace pulls from sources nothing else in this graph reads
directly:
  - node_timings: state["node_timings"], populated by graph.py's own
    per-node timing wrapper — not by any node itself.
  - every MCP tool call, with server/tool/duration/success:
    runtime.context.mcp.get_call_log() — already scoped to exactly this
    run, since a fresh MCPClientManager is created per
    run_recommendation call.
  - every LLM call, with model and token usage: mealsight.providers'
    process-wide MistralProvider/GroqProvider call logs, filtered down
    to this run by trace_id — they're shared singletons across every
    run in the process's lifetime, unlike the MCP manager, so filtering
    matters here in a way it doesn't for MCP calls.
  - the ranking table: state["matched_recipes"], already computed by
    match_rank (node 7).
  - errors and retries: MCP calls with success=False or more than one
    attempt, read straight from the same call log.
  - relaxations: search_recipes' own stream messages, which already say
    in plain language exactly what was relaxed and why.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.providers import get_audio_provider, get_text_provider
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.present")

NODE_NAME = "present"


def _ranking_table(matched_recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "recipe_id": r.get("recipe_id"),
            "name": r.get("name"),
            "match_score": r.get("match_score"),
            "composite_score": r.get("composite_score"),
            "can_cook": r.get("can_cook"),
        }
        for r in matched_recipes
    ]


def _llm_calls(trace_id: str | None) -> list[dict[str, Any]]:
    calls = [*get_text_provider().get_call_log(), *get_audio_provider().get_call_log()]
    if trace_id is None:
        return calls
    return [call for call in calls if call.get("trace_id") == trace_id]


def _errors_and_retries(
    mcp_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors = [call for call in mcp_calls if not call.get("success")]
    retries = [call for call in mcp_calls if call.get("attempts", 1) > 1]
    return errors, retries


def _relaxation_messages(stream_messages: list[str]) -> list[str]:
    return [
        message
        for message in stream_messages
        if message.startswith("[search_recipes]")
        and any(word in message for word in ("Dropping", "raising", "dropping"))
    ]


async def present(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    try:
        mcp_calls = runtime.context.mcp.get_call_log()
    except Exception:
        logger.error("present_mcp_call_log_unexpected_failure", exc_info=True)
        mcp_calls = []

    try:
        llm_calls = _llm_calls(state.get("trace_id"))
    except Exception:
        logger.error("present_llm_call_log_unexpected_failure", exc_info=True)
        llm_calls = []

    errors, retries = _errors_and_retries(mcp_calls)

    trace: dict[str, Any] = {
        "node_timings": state.get("node_timings") or [],
        "mcp_calls": mcp_calls,
        "llm_calls": llm_calls,
        "ranking": _ranking_table(state.get("matched_recipes") or []),
        "errors": errors,
        "retries": retries,
        "relaxations": _relaxation_messages(state.get("stream_messages") or []),
    }

    has_recommendation = bool((state.get("top_recommendation") or {}).get("available"))
    completion_message = (
        f"[{NODE_NAME}] Done — recommendation ready."
        if has_recommendation
        else f"[{NODE_NAME}] Done — no recipe could be recommended this run."
    )

    logger.info(
        "node_finished",
        node=NODE_NAME,
        mcp_calls=len(mcp_calls),
        llm_calls=len(llm_calls),
        errors=len(errors),
    )
    return {"processing_trace": [trace], "stream_messages": [completion_message]}
