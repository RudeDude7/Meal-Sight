"""Tests for mealsight.agent.mcp_client.MCPClientManager.

Two kinds of test here, deliberately: a handful start the three REAL
MCP servers as real subprocesses (slower, but the only way to actually
prove "starts all three servers and passes health check" is true of
the real thing) — and a couple use a monkeypatched fastmcp.Client to
prove the specific failure-handling behavior (a missing tool, naming
exactly which server) deterministically, without needing to actually
break a real server on purpose.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from mealsight.agent.mcp_client import (
    EXPECTED_TOOLS,
    MCPClientManager,
    MCPServerStartupError,
    ServerName,
)


async def test_bad_server_name_raises_a_clear_error_without_needing_a_running_manager() -> None:
    manager = MCPClientManager()
    # No start() call at all — server_name isn't in self._clients either
    # way (never started, or genuinely unknown), and call_tool's own
    # contract is to raise ValueError immediately for this, not return
    # a ToolCallResult.
    with pytest.raises(ValueError, match="Unknown MCP server"):
        await manager.call_tool(cast(ServerName, "not_a_real_server"), "some_tool")


async def test_manager_starts_all_three_servers_health_checks_and_calls_a_real_tool() -> None:
    async with MCPClientManager() as manager:
        inventory = await manager.list_tool_inventory()

        assert set(inventory) == set(EXPECTED_TOOLS)
        for server, expected in EXPECTED_TOOLS.items():
            assert expected <= set(inventory[server]), f"{server} missing expected tools"

        result = await manager.call_tool("user_intelligence", "get_user_profile", {})
        assert result.success is True
        assert result.error is None
        assert isinstance(result.data, dict)
        assert "household_size" in result.data


async def test_shutdown_clears_manager_state_and_further_calls_fail_clearly() -> None:
    manager = MCPClientManager()
    await manager.start()
    await manager.shutdown()

    with pytest.raises(ValueError, match="Unknown MCP server"):
        await manager.call_tool("user_intelligence", "get_user_profile", {})

    # Idempotent — calling shutdown again after it already ran must not raise.
    await manager.shutdown()


async def test_timeout_fires_and_returns_a_structured_failure_not_an_exception() -> None:
    manager = MCPClientManager(call_timeout_seconds=0.0001, max_retries=1)
    async with manager:
        result = await manager.call_tool("user_intelligence", "get_user_profile", {})

    assert result.success is False
    assert result.data is None
    assert result.error is not None


class _FakeToolsResult:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClient:
    """A minimal stand-in for fastmcp.Client, used only to prove
    MCPClientManager.start()'s own health-check failure path — naming
    the specific server and the specific missing tools — without
    needing to actually break a real server subprocess on purpose."""

    def __init__(self, missing_tool_server: str, missing_tool: str) -> None:
        self._missing_tool_server = missing_tool_server
        self._missing_tool = missing_tool

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def list_tools(self) -> list[_FakeToolsResult]:
        server = getattr(self, "_server_name", None)
        tools = EXPECTED_TOOLS[cast(ServerName, server)] if server else frozenset()
        names = tools - {self._missing_tool} if server == self._missing_tool_server else tools
        return [_FakeToolsResult(name) for name in names]


async def test_health_check_failure_names_the_server_and_missing_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_client_factory(transport: Any, timeout: float) -> _FakeClient:
        # StdioTransport carries the server name in its own args list
        # (["-m", "mealsight.mcp_servers.<server_name>"]) — pulled back
        # out here so one fake can answer correctly for all three.
        module_arg = transport.args[-1]
        server_name = module_arg.rsplit(".", 1)[-1]
        client = _FakeClient(missing_tool_server="pantry_manager", missing_tool="update_pantry")
        client._server_name = server_name  # type: ignore[attr-defined]
        return client

    monkeypatch.setattr("mealsight.agent.mcp_client.Client", fake_client_factory)

    manager = MCPClientManager()
    with pytest.raises(MCPServerStartupError, match="pantry_manager") as exc_info:
        await manager.start()

    assert "update_pantry" in str(exc_info.value)
