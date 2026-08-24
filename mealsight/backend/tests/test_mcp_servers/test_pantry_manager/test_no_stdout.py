"""Confirms nothing is written to stdout during tool execution — the
stdio transport speaks the MCP protocol over stdout, so a stray print()
or a logger still configured to write there would corrupt the stream.
Runs a mix of happy-path and error-path calls (including one that
triggers a structured not_found result) to check across every code path
a tool can take, not just the successful one."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from tests.test_mcp_servers.test_pantry_manager.conftest import insert_pantry_item


async def test_nothing_is_written_to_stdout_during_tool_calls(
    mcp_client: Client[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    await insert_pantry_item(name="onion", quantity=2.0)

    await mcp_client.call_tool(
        "update_pantry", {"items": [{"name": "milk", "quantity": 1.0, "unit": "liter", "category": "dairy"}]}
    )
    await mcp_client.call_tool("get_pantry", {})
    await mcp_client.call_tool("get_pantry", {"freshness_filter": "bogus"})  # validation path
    await mcp_client.call_tool("remove_items", {"items": [{"name": "onion", "quantity_used": 1.0}]})
    await mcp_client.call_tool(
        "remove_items", {"items": [{"name": "does-not-exist", "quantity_used": 1.0}]}
    )  # not-found-in-pantry path
    await mcp_client.call_tool("flag_expiring", {})
    await mcp_client.call_tool("get_grocery_list", {})  # not_found path, no active list

    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout output: {captured.out!r}"
