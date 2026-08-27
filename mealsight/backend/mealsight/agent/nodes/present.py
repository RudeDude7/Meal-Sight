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

THE OTHER THING THIS NODE DOES: records one interaction_history row via
the user_intelligence MCP server's own record_interaction tool — every
completed run, regardless of outcome, including a terminal run (no
usable input at all) and a run that found nothing cookable. This is
deliberately a SEPARATE record from meal_history (log_meal/rate_meal),
which only ever gets a row on a confirmed cook — interaction_history is
every REQUEST. Reached through runtime.context.mcp.call_tool, never by
importing mealsight.user_intelligence directly — this project's own
established rule (every other agent node already follows it) that an
agent node only ever reaches a domain module through the MCP client,
since the real MCP servers run as separate subprocesses even though the
Python package is technically importable from this process too.
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


def _attempted_modalities(state: MealSightState) -> list[str]:
    unified = state.get("unified_request")
    if unified is not None:
        return list(unified.modalities_received)
    # Perception never ran far enough to merge anything (e.g. a
    # terminal run) — fall back to which raw inputs were actually
    # supplied, so a failed run still records what was ATTEMPTED.
    modalities = []
    if state.get("image_bytes"):
        modalities.append("vision")
    if state.get("audio_bytes"):
        modalities.append("audio")
    if state.get("text_input"):
        modalities.append("text")
    return modalities


def _ingredients_summary(state: MealSightState) -> str | None:
    vision = state.get("vision_result")
    if vision is None or not vision.identified_items:
        return None
    names = [item.name for item in vision.identified_items[:15]]
    suffix = f", and {len(vision.identified_items) - 15} more" if len(vision.identified_items) > 15 else ""
    return f"Found {vision.total_items_found} item(s): {', '.join(names)}{suffix}"


def _merged_constraints(state: MealSightState) -> dict[str, Any] | None:
    unified = state.get("unified_request")
    if unified is None:
        return None
    return {
        "servings": unified.servings,
        "max_cook_time_minutes": unified.max_cook_time_minutes,
        "dietary_restrictions": unified.dietary_restrictions,
        "cuisine_preference": unified.cuisine_preference,
        "avoid_ingredients": unified.avoid_ingredients,
        "avoid_dishes": unified.avoid_dishes,
        "mood_or_preference": unified.mood_or_preference,
        "protein_preference": unified.protein_preference,
        "occasion": unified.occasion,
    }


def _recommendation_summary(state: MealSightState) -> tuple[str | None, str | None, bool, float | None]:
    """Returns (recommended_recipe_id, recommended_recipe_name,
    any_cookable, top_match_score) — any_cookable and top_match_score
    are computed straight from matched_recipes (node 7's own candidate
    list), independent of whether reason (node 8) actually recommended
    anything, so they stay a true reflection of what was FOUND this run
    even on a run that ends in an explanation rather than a pick."""
    matched_recipes = state.get("matched_recipes") or []
    any_cookable = any(candidate.get("can_cook") for candidate in matched_recipes)
    scores = [
        candidate["match_score"] for candidate in matched_recipes if candidate.get("match_score") is not None
    ]
    top_match_score = max(scores) if scores else None

    top_recommendation = state.get("top_recommendation") or {}
    if not top_recommendation.get("available"):
        return None, None, any_cookable, top_match_score

    recipe_id = top_recommendation.get("recipe_id")
    name = next(
        (c.get("name") for c in matched_recipes if c.get("recipe_id") == recipe_id),
        None,
    )
    return recipe_id, name, any_cookable, top_match_score


async def _record_interaction(
    state: MealSightState, runtime: Runtime[AgentContext], *, final_response: str | None
) -> None:
    """Never raises out of this node — recording an interaction is a
    side effect this run's own result should never depend on; a failure
    here is logged and otherwise swallowed, the same "never raise out of
    a node" discipline present already applies to its own call-log
    reads above."""
    recipe_id, recipe_name, any_cookable, top_match_score = _recommendation_summary(state)
    audio_result = state.get("audio_result")
    try:
        await runtime.context.mcp.call_tool(
            "user_intelligence",
            "record_interaction",
            {
                "trace_id": state.get("trace_id"),
                "modalities": _attempted_modalities(state),
                "text_input": state.get("text_input"),
                "voice_transcript": audio_result.raw_transcript if audio_result else None,
                "ingredients_summary": _ingredients_summary(state),
                "merged_constraints": _merged_constraints(state),
                "recommended_recipe_id": recipe_id,
                "recommended_recipe_name": recipe_name,
                "any_cookable": any_cookable,
                "top_match_score": top_match_score,
                "final_response": final_response,
            },
        )
    except Exception:
        logger.error("present_record_interaction_failed", exc_info=True)


async def present(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        await _record_interaction(
            state,
            runtime,
            final_response=state.get("terminal_reason") or "No usable input was provided this run.",
        )
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

    await _record_interaction(state, runtime, final_response=state.get("final_response"))

    return {"processing_trace": [trace], "stream_messages": [completion_message]}
