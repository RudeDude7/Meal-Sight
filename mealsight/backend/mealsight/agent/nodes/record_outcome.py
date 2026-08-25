"""record_outcome — formerly log_learn; renamed this phase because its
old name implied real work this node cannot honestly do yet.

CONFIRMED before writing anything (per this phase's own instruction to
check first): every candidate action the original stub docstring named
turns out to be unavailable right now, not just unwise:

  - "increment times_recommended on the chosen recipe" — no MCP tool
    exposes this. recipe_engine's own EXPECTED_TOOLS (mealsight.agent.
    mcp_client) is exactly search_recipes, get_recipe, match_ingredients,
    scale_recipe, calculate_nutrition, find_substitutions — six tools,
    none of them a write path for times_recommended, even though that
    column exists on the recipes table itself.
  - "persist the processing trace" — there is no tool on any of the
    three servers to persist a trace externally (pantry_manager and
    user_intelligence's own tool lists have nothing analytics-shaped
    either). processing_trace already flows forward in state to present
    (node 11) for free, by the graph's own ordinary state-passing — that
    part needs no action from this node at all.
  - "apply any explicit preference update the request itself stated" —
    user_intelligence's update_preferences tool genuinely exists, but
    nothing upstream ever marks a stated preference as PERSISTENT versus
    "for this meal only." UnifiedMealRequest's own cuisine_preference/
    mood_or_preference/protein_preference/dietary_restrictions are all
    per-request fields with no such distinction recorded anywhere in
    mealsight.perception. Calling update_preferences from any of them
    would be inventing an intent the user never actually expressed —
    exactly the kind of thing this project's own established convention
    (mealsight.recipe_engine.calculate_nutrition's coverage_note,
    reason's own DimensionReasoning.applies=False) says to be honest
    about instead of quietly padding.

So: this node calls no MCP tool at all, and mutates nothing beyond its
own one stream message — reporting plainly that nothing was actionable,
which is a true statement about this run, not a placeholder for future
work pretending to already be done. When a real times_recommended write
path or a real persistent-vs-transient preference signal exists, this
is where that logic belongs; until then, padding it with a call that
doesn't correspond to anything real would be worse than an honest
no-op.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.state import MealSightState
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.record_outcome")

NODE_NAME = "record_outcome"


async def record_outcome(state: MealSightState) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    logger.info("node_finished", node=NODE_NAME, action="none")
    return {
        "stream_messages": [
            f"[{NODE_NAME}] Nothing to record yet — no tool exists to update recipe "
            "stats or persist this run, and nothing upstream marked a stated preference "
            "as permanent rather than just for this meal."
        ]
    }
