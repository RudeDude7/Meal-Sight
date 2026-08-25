"""build_graph — wires the eleven-node MealSight LangGraph pipeline.

Every node is a stub in this phase (mealsight.agent.nodes) — what this
module actually builds is the graph SHAPE (eleven nodes, wired
sequentially, one clear start and one clear end), the state schema
(mealsight.agent.state.MealSightState), and confirmation that the whole
thing compiles and runs end to end. A later session fills in each
node's real logic by editing that node's own file under mealsight.
agent.nodes/ — nothing about this file needs to change to do that,
since NODE_ORDER and the node functions it wires are already exactly
what a real implementation would use.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mealsight.agent.context import AgentContext
from mealsight.agent.nodes import (
    generate_output,
    get_context,
    log_learn,
    match_rank,
    merge,
    perceive,
    present,
    reason,
    search_recipes,
    update_pantry,
    validate_input,
)
from mealsight.agent.state import MealSightState

# The eleven nodes, in the exact sequential order they run — the single
# source of truth both build_graph and this module's own tests read
# from, so "how many nodes" and "what order" are never duplicated.
NODE_ORDER: tuple[str, ...] = (
    "validate_input",
    "perceive",
    "merge",
    "update_pantry",
    "get_context",
    "search_recipes",
    "match_rank",
    "reason",
    "generate_output",
    "log_learn",
    "present",
)

_NODE_FUNCTIONS: dict[str, Any] = {
    "validate_input": validate_input,
    "perceive": perceive,
    "merge": merge,
    "update_pantry": update_pantry,
    "get_context": get_context,
    "search_recipes": search_recipes,
    "match_rank": match_rank,
    "reason": reason,
    "generate_output": generate_output,
    "log_learn": log_learn,
    "present": present,
}


def build_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Builds and compiles the eleven-node graph, wired sequentially:
    START -> validate_input -> perceive -> merge -> update_pantry ->
    get_context -> search_recipes -> match_rank -> reason ->
    generate_output -> log_learn -> present -> END.

    Purely sequential in this phase — no conditional routing, no
    parallel branches at the graph level (individual nodes may run
    concurrent work internally, e.g. perceive's own three analyze_*
    calls, without that being a graph-level branch). A later session
    is free to introduce real branching (e.g. skipping update_pantry
    when there's no vision_result at all) without this function's own
    shape needing to change first.

    context_schema=AgentContext is what lets nodes 1-5 (phase 6.2)
    reach the running MCPClientManager via a `runtime: Runtime[
    AgentContext]` second parameter — LangGraph supplies runtime only
    to node functions that actually declare it, so nodes 6-11 (still
    plain, state-only stubs) are unaffected by this.
    """
    builder = StateGraph(MealSightState, context_schema=AgentContext)

    for name in NODE_ORDER:
        builder.add_node(name, _NODE_FUNCTIONS[name])

    builder.add_edge(START, NODE_ORDER[0])
    # A pairwise zip is deliberately shorter than NODE_ORDER by one —
    # strict=False, not an oversight.
    for current_node, next_node in zip(NODE_ORDER, NODE_ORDER[1:], strict=False):
        builder.add_edge(current_node, next_node)
    builder.add_edge(NODE_ORDER[-1], END)

    return builder.compile()
