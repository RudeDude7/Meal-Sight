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

import inspect
import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

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
    """Wraps a node function so every call does three things the node
    itself never has to: records one {"node", "duration_ms"} entry in
    node_timings, and — new this phase — emits a node_start event before
    calling fn and a node_complete event after, via runtime.context.
    stream (mealsight.agent.context.StreamSink), if this run has one.

    Unlike the phase-6.4 version of this wrapper (which used functools.
    wraps so its OWN advertised signature matched fn's, letting LangGraph
    decide whether to inject runtime by inspecting fn), this wrapper now
    ALWAYS declares (state, runtime) itself, regardless of what fn
    declares — LangGraph therefore always injects runtime into every
    node's own wrapped call, which is what lets node_start/node_complete
    fire uniformly for all eleven nodes (including ones like
    validate_input and record_outcome that have no reason to declare
    runtime themselves, since they call no MCP tool and emit no other
    progress). Whether to actually forward runtime to fn is decided once,
    at wrap time, by inspecting fn's OWN real signature — a node that
    never declared runtime before this phase still never receives it
    now; only this wrapper's own outward-facing signature changed.
    """
    fn_accepts_runtime = "runtime" in inspect.signature(fn).parameters

    async def wrapped(state: Any, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        stream = runtime.context.stream if runtime.context is not None else None
        if stream is not None:
            stream.emit("node_start", node=node_name)

        started = time.monotonic()
        result = await (fn(state, runtime) if fn_accepts_runtime else fn(state))
        duration_ms = round((time.monotonic() - started) * 1000, 2)

        if stream is not None:
            stream.emit("node_complete", node=node_name, duration_ms=duration_ms)

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
