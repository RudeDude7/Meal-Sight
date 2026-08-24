"""Tests for mealsight.agent.graph.build_graph — the stub graph shape,
end-to-end execution, and trace-id propagation. No MCP servers or
providers involved: every node in this phase is a stub."""

from __future__ import annotations

from typing import Any

import pytest

import mealsight.agent.graph as graph_module
from mealsight.agent.graph import NODE_ORDER, build_graph
from mealsight.utils.logging import bind_trace_id, current_trace_id


def test_graph_compiles_with_all_eleven_nodes() -> None:
    assert len(NODE_ORDER) == 11
    graph = build_graph()
    node_names = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert node_names == set(NODE_ORDER)


async def test_graph_runs_end_to_end_and_accumulates_eleven_stream_messages() -> None:
    graph = build_graph()
    result = await graph.ainvoke({"stream_messages": []})

    assert len(result["stream_messages"]) == 11
    for node_name, message in zip(NODE_ORDER, result["stream_messages"], strict=True):
        assert message.startswith(f"[{node_name}]")


async def test_trace_id_is_consistent_across_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_trace_ids: list[str | None] = []

    async def spy_get_context(state: dict[str, Any]) -> dict[str, Any]:
        seen_trace_ids.append(current_trace_id())
        return {"stream_messages": ["spy:get_context"]}

    async def spy_present(state: dict[str, Any]) -> dict[str, Any]:
        seen_trace_ids.append(current_trace_id())
        return {"stream_messages": ["spy:present"]}

    monkeypatch.setitem(graph_module._NODE_FUNCTIONS, "get_context", spy_get_context)
    monkeypatch.setitem(graph_module._NODE_FUNCTIONS, "present", spy_present)

    trace_id = "test-trace-consistency-check"
    bind_trace_id(trace_id)

    graph = build_graph()
    await graph.ainvoke({"stream_messages": []})

    assert seen_trace_ids == [trace_id, trace_id]
