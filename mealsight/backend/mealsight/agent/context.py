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

from mealsight.agent.mcp_client import MCPClientManager


@dataclass(slots=True)
class AgentContext:
    """context_schema for MealSight's graph. mcp is the already-started
    MCPClientManager for this run — every node that calls a real MCP
    tool receives it via `runtime.context.mcp`, never by constructing
    or starting a manager of its own."""

    mcp: MCPClientManager
