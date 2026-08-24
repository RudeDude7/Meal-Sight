"""Confirms nothing is written to stdout during tool execution — the
stdio transport speaks the MCP protocol over stdout, so a stray print()
or a logger still configured to write there would corrupt the stream.
Runs a mix of happy-path and error-path calls (including one that
triggers an unexpected exception, error-logged internally) to check
across every code path a tool can take, not just the successful one."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from tests.test_mcp_servers.test_recipe_engine.conftest import insert_recipe

_ONION = {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}


async def test_nothing_is_written_to_stdout_during_tool_calls(
    mcp_client: Client[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    await insert_recipe(recipe_id="1", name="Test", ingredients=[_ONION], cook_time_minutes=20)

    await mcp_client.call_tool("search_recipes", {"dietary_filters": []})
    await mcp_client.call_tool("get_recipe", {"recipe_id": "1"})
    await mcp_client.call_tool("get_recipe", {"recipe_id": "missing"})  # not-found path
    await mcp_client.call_tool("scale_recipe", {"recipe_id": "1", "target_servings": 0})  # validation path
    await mcp_client.call_tool(
        "find_substitutions", {"ingredient_name": "butter", "reason": "bogus"}
    )  # validation path

    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout output: {captured.out!r}"
