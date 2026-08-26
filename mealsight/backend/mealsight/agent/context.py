"""AgentContext — the LangGraph runtime context every node that needs
the MCP client manager uses to reach it.

FINDING, reported before writing any node logic: as of the previous
session (phase 6.1), the MCP manager was NOT actually threaded through
to nodes at all — runner.py opened it purely to satisfy "starts and
stops on every real run," but no node had any way to reach it, since
every node function took only `state` as its argument and nothing in
build_graph or run_recommendation passed the manager anywhere a node
could read it from. This module is what actually closes that gap, using
LangGraph's own supported mechanism for exactly this (context_schema on
StateGraph, a `runtime: Runtime[AgentContext]` second parameter on any
node that needs it) rather than smuggling the manager through
MealSightState itself — state is meant to be the graph's own data,
serializable in principle, not a place to stash a live subprocess-owning
object. Confirmed live (a small throwaway graph before touching any
real node) that LangGraph correctly supplies runtime only to node
functions that declare the second parameter, leaving single-argument
stub nodes (6-11, unchanged this session) completely unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mealsight.agent.mcp_client import MCPClientManager


class StreamSink(Protocol):
    """What a node calls to push a live progress event out of the graph,
    if anyone's listening — deliberately just this one, plain, SYNCHRONOUS
    method (no await; asyncio.Queue.put_nowait is itself non-blocking) so
    every node's own call site stays exactly as simple as appending to
    stream_messages already is.

    Defined here, in mealsight.agent, as a Protocol rather than importing
    mealsight.api.streaming.SessionStream directly — the agent layer
    knows "something I can emit named events to, if given one," never
    that the concrete implementation is a WebSocket fan-out buffer. That
    stays mealsight.api's own concern; mealsight.agent must not depend on
    it, only the reverse.

    event_type is one of mealsight.api.messages' own message-type names
    ("node_start", "ingredient_found", "recipe_match", "recommendation",
    ...); fields are whatever that message type's own pydantic model
    needs beyond session_id/timestamp, which the concrete implementation
    stamps on itself.
    """

    def emit(self, event_type: str, **fields: Any) -> None: ...


@dataclass(slots=True)
class AgentContext:
    """context_schema for MealSight's graph. mcp is the already-started
    MCPClientManager for this run — every node that calls a real MCP
    tool receives it via `runtime.context.mcp`, never by constructing
    or starting a manager of its own.

    stream is None for every standalone run_recommendation call that
    doesn't pass one (every script, every test, unchanged) — every node
    that emits progress checks for None first, exactly the same
    "presence of a capability, not a guarantee of one" pattern this
    project already uses for the MCP manager itself before phase 6.1."""

    mcp: MCPClientManager
    stream: StreamSink | None = None
