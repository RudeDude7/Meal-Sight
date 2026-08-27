"""MCPClientManager — launches all three MealSight MCP servers
(recipe_engine, pantry_manager, user_intelligence) as real stdio
subprocesses and holds their sessions open for the lifetime of one
recommendation.

call_tool(server, tool_name, arguments) is the single entry point every
agent node uses to reach any of the nineteen tools across the three
servers — it never raises for a transport-level failure (one retry,
then a structured ToolCallResult with success=False), so a node can
reason about a failed tool call as ordinary data instead of wrapping
every single call in its own try/except.

Every call_tool invocation is also recorded in-memory (get_call_log) —
one entry per CALL (not per attempt), the same server/tool/duration_ms/
success shape already logged, plus how many attempts it took. present
(node 11) reads this to build processing_trace: a fresh
MCPClientManager is created per run_recommendation call (never a shared
singleton the way the LLM providers in mealsight.providers are), so
this call log is already correctly scoped to exactly one run with no
trace_id filtering needed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.mcp_client")

# backend/mealsight/agent/mcp_client.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]

ServerName = Literal["recipe_engine", "pantry_manager", "user_intelligence"]

# The tools each server is documented to expose (recipe_engine and
# pantry_manager: six each, phase 2.4/3.3; user_intelligence: seven,
# phase 4.3 plus rate_meal added in the cook-confirmation phase) — the
# health check below fails loudly if a server doesn't advertise every
# one of these, rather than letting a partially-broken server silently
# join the pool.
EXPECTED_TOOLS: dict[ServerName, frozenset[str]] = {
    "recipe_engine": frozenset(
        {
            "search_recipes",
            "get_recipe",
            "match_ingredients",
            "scale_recipe",
            "calculate_nutrition",
            "find_substitutions",
        }
    ),
    "pantry_manager": frozenset(
        {
            "update_pantry",
            "get_pantry",
            "remove_items",
            "flag_expiring",
            "create_grocery_list",
            "get_grocery_list",
        }
    ),
    "user_intelligence": frozenset(
        {
            "get_user_profile",
            "update_preferences",
            "log_meal",
            "rate_meal",
            "get_meal_history",
            "check_repetition",
            "get_context_signals",
        }
    ),
}

DEFAULT_CALL_TIMEOUT_SECONDS = 30.0
DEFAULT_STARTUP_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 1


class MCPServerStartupError(RuntimeError):
    """Raised by MCPClientManager.start() (and therefore __aenter__)
    when a server fails to start at all, or starts but is missing one
    or more of its expected tools. Names every failing server and the
    specific reason — never a bare "something went wrong" — and any
    server that DID start successfully before the failure is still
    torn down before this is raised, so a failed start never leaks a
    live subprocess."""


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """What call_tool always returns instead of either raising (for a
    transport failure) or handing back a raw, un-parsed protocol
    object. success=True means data holds the tool's own parsed JSON
    result (which may itself be one of mealsight.mcp_servers.errors'
    structured not_found/validation_error/internal_error shapes — that
    is a successful CALL that happens to report a business-level
    problem, not a transport failure, so it still comes back as
    success=True here); success=False means the call itself never
    completed, even after one retry, and error names why."""

    success: bool
    data: Any = None
    error: str | None = None


class _StderrForwarder:
    """Captures a managed server's stderr into this project's own
    structured logger instead of either the default (fastmcp's own
    log_file default is sys.stderr passthrough — real output, but with
    no service attribution and no trace_id) or letting it go anywhere
    it could be silently lost (easy to happen under a test/CI harness
    that doesn't surface a subprocess's inherited stderr at all).

    StdioTransport's own log_file parameter is handed directly to the
    real subprocess as its stderr target, which means it has to be a
    genuine OS-backed file object (something with a real .fileno()) —
    a plain Python object with just a .write() method is NOT enough
    (confirmed the hard way: fastmcp's own subprocess creation raised
    "'_StderrForwarder' object has no attribute 'fileno'" the first
    time this was tried with a duck-typed stream). So this class opens
    a real OS pipe (os.pipe()), hands the write end — wrapped as a real
    file via os.fdopen, which does have a working fileno() — to
    StdioTransport as log_file, and reads the other end in a small
    background thread, forwarding each line to the real logger as it
    arrives. The thread is a daemon specifically so it can never block
    process shutdown even if it hasn't drained the pipe yet.
    """

    def __init__(self, server_name: str) -> None:
        self._server_name = server_name
        self._logger = get_logger(f"mealsight.agent.mcp_client.{server_name}")
        read_fd, write_fd = os.pipe()
        self._write_file: TextIO = os.fdopen(write_fd, "w")
        self._read_file: TextIO = os.fdopen(read_fd, "r")
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    @property
    def file(self) -> TextIO:
        """The real, fileno()-backed file object to hand StdioTransport
        as log_file — the write end of the pipe."""
        return self._write_file

    def _pump(self) -> None:
        try:
            for raw_line in self._read_file:
                line = raw_line.rstrip("\n")
                if line:
                    self._logger.info("mcp_server_stderr", server=self._server_name, line=line)
        except ValueError:
            # The read end was closed out from under an in-flight
            # readline (a shutdown race, not a real error) — the loop
            # ending here is exactly the shutdown behavior wanted.
            pass

    def close(self) -> None:
        """Closes the write end so the subprocess (once it exits) and
        this forwarder's own background thread both see EOF and stop
        cleanly; then joins that thread briefly so shutdown() doesn't
        return while it's still mid-line."""
        self._write_file.close()
        self._thread.join(timeout=2.0)


class MCPClientManager:
    """Owns all three MCP server subprocesses for the lifetime of one
    recommendation. Use as an async context manager (`async with
    MCPClientManager() as manager:`), or call start()/shutdown()
    directly if you need finer control over the lifecycle."""

    def __init__(
        self,
        call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._call_timeout_seconds = call_timeout_seconds
        self._startup_timeout_seconds = startup_timeout_seconds
        self._max_retries = max_retries
        self._clients: dict[ServerName, Client[Any]] = {}
        self._forwarders: dict[ServerName, _StderrForwarder] = {}
        self._exit_stack = AsyncExitStack()
        self._started = False
        self._call_log: list[dict[str, Any]] = []

    async def start(self) -> None:
        """Launches all three servers CONCURRENTLY (asyncio.gather, not
        one after another), waits for each to finish initializing, then
        runs a health check against each: list its tools, and confirm
        every name in EXPECTED_TOOLS[server] is actually present.

        Raises MCPServerStartupError, naming every failing server and
        why, if any server fails to start OR is missing expected
        tools — and tears down every server that did start successfully
        first, so a failed start never leaves an orphaned subprocess
        running. Idempotent: calling start() again after a successful
        start is a no-op.
        """
        if self._started:
            return

        server_names = list(EXPECTED_TOOLS)
        results = await asyncio.gather(
            *(self._start_one(name) for name in server_names), return_exceptions=True
        )
        failures = [
            f"{name}: {result}"
            for name, result in zip(server_names, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            await self.shutdown()
            raise MCPServerStartupError(
                "One or more MCP servers failed to start: " + "; ".join(failures)
            )

        self._started = True
        logger.info("mcp_manager_started", servers=server_names)

    async def _start_one(self, server_name: ServerName) -> None:
        forwarder = _StderrForwarder(server_name)
        self._forwarders[server_name] = forwarder
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", f"mealsight.mcp_servers.{server_name}"],
            cwd=str(BACKEND_DIR),
            log_file=forwarder.file,
            keep_alive=True,
        )
        client: Client[Any] = Client(transport, timeout=self._startup_timeout_seconds)
        await self._exit_stack.enter_async_context(client)

        tools = await asyncio.wait_for(client.list_tools(), timeout=self._startup_timeout_seconds)
        found = {t.name for t in tools}
        missing = EXPECTED_TOOLS[server_name] - found
        if missing:
            raise MCPServerStartupError(
                f"{server_name} started but is missing expected tools "
                f"{sorted(missing)} (found: {sorted(found)})"
            )

        self._clients[server_name] = client
        logger.info("mcp_server_health_check_passed", server=server_name, tools=sorted(found))

    async def shutdown(self) -> None:
        """Terminates every subprocess and closes every session — even
        ones that never fully finished starting, since a partially-open
        AsyncExitStack still knows how to unwind whatever it managed to
        open. Idempotent: safe to call more than once, and safe to call
        even if start() itself raised."""
        await self._exit_stack.aclose()
        self._clients.clear()
        for forwarder in self._forwarders.values():
            forwarder.close()
        self._forwarders.clear()
        self._started = False
        logger.info("mcp_manager_shutdown")

    async def __aenter__(self) -> MCPClientManager:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.shutdown()

    async def call_tool(
        self, server: ServerName, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        """The single entry point for calling any tool on any managed
        server. One retry is attempted automatically on a transport
        failure (a timeout, a dropped connection, anything that isn't
        the tool itself just returning a business-level error); if the
        retry also fails, a structured ToolCallResult(success=False,
        error=...) comes back instead of letting the exception
        propagate — every tool call this manager makes is logged
        (server, tool, duration_ms, success, attempt), which is what
        becomes this project's own processing trace.

        Raises ValueError immediately — not a ToolCallResult — if
        server isn't one of the three managed servers. That's a
        programmer error in the CALLER (a typo'd server name), not a
        runtime condition worth degrading gracefully around.
        """
        if server not in self._clients:
            raise ValueError(
                f"Unknown MCP server {server!r}; expected one of {sorted(EXPECTED_TOOLS)}."
            )

        client = self._clients[server]
        last_error: str | None = None
        attempts = self._max_retries + 1

        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, arguments or {}, timeout=self._call_timeout_seconds),
                    timeout=self._call_timeout_seconds,
                )
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                logger.info(
                    "mcp_tool_call",
                    server=server,
                    tool=tool_name,
                    duration_ms=duration_ms,
                    success=True,
                    attempt=attempt,
                )
                self._call_log.append(
                    {
                        "server": server,
                        "tool": tool_name,
                        "duration_ms": duration_ms,
                        "success": True,
                        "attempts": attempt,
                    }
                )
                return ToolCallResult(success=True, data=result.data)
            except Exception as exc:
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "mcp_tool_call_failed",
                    server=server,
                    tool=tool_name,
                    duration_ms=duration_ms,
                    success=False,
                    attempt=attempt,
                    error=last_error,
                )

        logger.error("mcp_tool_call_exhausted", server=server, tool=tool_name, error=last_error)
        self._call_log.append(
            {
                "server": server,
                "tool": tool_name,
                "duration_ms": duration_ms,
                "success": False,
                "attempts": attempts,
                "error": last_error,
            }
        )
        return ToolCallResult(success=False, error=last_error)

    def get_call_log(self) -> list[dict[str, Any]]:
        """Every call_tool invocation this manager has made so far, one
        entry per call (not per attempt) — what present (node 11) reads
        to build the MCP portion of processing_trace."""
        return list(self._call_log)

    async def list_tool_inventory(self) -> dict[ServerName, list[str]]:
        """Returns {server: [tool names]} for every currently connected
        server. Not used by call_tool itself — this is for
        introspection/verification, the same thing this phase's own
        live verification prints directly."""
        inventory: dict[ServerName, list[str]] = {}
        for name, client in self._clients.items():
            tools = await client.list_tools()
            inventory[name] = sorted(t.name for t in tools)
        return inventory
