"""Confirms nothing is written to stdout during tool execution — the
stdio transport speaks the MCP protocol over stdout, so a stray print()
or a logger still configured to write there would corrupt the stream.
Runs a mix of happy-path and error-path calls to check across every
code path a tool can take, not just the successful one."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastmcp import Client

from tests.test_mcp_servers.test_user_intelligence.conftest import insert_recipe


async def test_nothing_is_written_to_stdout_during_tool_calls(
    mcp_client: Client[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    await insert_recipe(recipe_id="r1", name="Tacos", cuisine="mexican", ingredients=["beef"])

    await mcp_client.call_tool("get_user_profile", {})
    await mcp_client.call_tool(
        "update_preferences", {"preference_type": "household_size", "value": 3}
    )
    await mcp_client.call_tool(
        "update_preferences", {"preference_type": "favorite_color", "value": "blue"}
    )  # validation path
    await mcp_client.call_tool(
        "log_meal",
        {
            "recipe_id": "r1",
            "recipe_name": "Tacos",
            "cuisine": "mexican",
            "meal_type": "dinner",
            "date": date.today().isoformat(),
            "rating": 5,
        },
    )
    await mcp_client.call_tool(
        "log_meal",
        {
            "recipe_id": None,
            "recipe_name": "Bad",
            "cuisine": None,
            "meal_type": None,
            "date": date.today().isoformat(),
            "rating": 99,
        },
    )  # validation path
    await mcp_client.call_tool("get_meal_history", {})
    await mcp_client.call_tool("check_repetition", {"recipe_id": "r1"})
    await mcp_client.call_tool("check_repetition", {"recipe_id": "does-not-exist"})  # not-found path
    await mcp_client.call_tool("get_context_signals", {})

    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout output: {captured.out!r}"
