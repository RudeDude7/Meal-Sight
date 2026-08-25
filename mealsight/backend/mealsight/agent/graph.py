"""build_graph — wires the eleven-node MealSight LangGraph pipeline.

Every node is now real (phases 6.2-6.4). What this module builds is the
graph SHAPE (eleven nodes, wired sequentially, one clear start and one
clear end), the state schema (mealsight.agent.state.MealSightState),
and — new this phase — a per-node timing wrapper feeding
state["node_timings"], which present (node 11) needs to build its own
processing_trace without any of the other ten node files having to
instrument themselves.

log_learn was renamed record_outcome this phase: its own original name
implied real learning/logging work that turned out not to exist yet at
recommendation time (see record_outcome.py's own module docstring for
why) — NODE_ORDER's own entry changed with it, and nothing in this
project's tests hardcoded the old string, so this was a safe, contained
rename.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mealsight.agent.context import AgentContext
from mealsight.agent.nodes import (
    generate_output,
    get_context,
    match_rank,
    merge,
    perceive,
    present,
    reason,
    record_outcome,
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
    "record_outcome",
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
    "record_outcome": record_outcome,
    "present": present,
}


def _timed(node_name: str, fn: Any) -> Any:
    """Wraps a node function so every call — success or (contract-
    violating) failure — appends one {"node", "duration_ms"} record to
    node_timings, without changing the wrapped function's own observable
    signature. functools.wraps matters here for more than attribution:
    inspect.signature() follows __wrapped__ by default, and LangGraph's
    own runtime-injection (langgraph._internal._runnable) decides
    whether to pass `runtime` by inspecting the node callable's real
    parameter list — confirmed live, with a small throwaway graph,
    before wiring this into the real one, that a functools.wraps-wrapped
    node still receives runtime exactly when the ORIGINAL function
    declares it, whether that original takes (state) or (state,
    runtime).
    """

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        result = await fn(*args, **kwargs)
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        return {**result, "node_timings": [{"node": node_name, "duration_ms": duration_ms}]}

    return wrapped


def build_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Builds and compiles the eleven-node graph, wired sequentially:
    START -> validate_input -> perceive -> merge -> update_pantry ->
    get_context -> search_recipes -> match_rank -> reason ->
    generate_output -> record_outcome -> present -> END.

    Purely sequential in this phase — no conditional routing, no
    parallel branches at the graph level (individual nodes may run
    concurrent work internally, e.g. perceive's own three analyze_*
    calls, without that being a graph-level branch). A later session
    is free to introduce real branching (e.g. skipping update_pantry
    when there's no vision_result at all) without this function's own
    shape needing to change first.

    context_schema=AgentContext is what lets any node reach the running
    MCPClientManager via a `runtime: Runtime[AgentContext]` second
    parameter — LangGraph supplies runtime only to node functions that
    actually declare it. Every node is wrapped in _timed before being
    added, reading _NODE_FUNCTIONS fresh on every call (not once at
    import time), so a test that monkeypatches _NODE_FUNCTIONS[name]
    still gets its own replacement timed and wired correctly.
    """
    builder = StateGraph(MealSightState, context_schema=AgentContext)

    for name in NODE_ORDER:
        builder.add_node(name, _timed(name, _NODE_FUNCTIONS[name]))

    builder.add_edge(START, NODE_ORDER[0])
    # A pairwise zip is deliberately shorter than NODE_ORDER by one —
    # strict=False, not an oversight.
    for current_node, next_node in zip(NODE_ORDER, NODE_ORDER[1:], strict=False):
        builder.add_edge(current_node, next_node)
    builder.add_edge(NODE_ORDER[-1], END)

    return builder.compile()
