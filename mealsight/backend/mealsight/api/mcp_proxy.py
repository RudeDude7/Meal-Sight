"""unwrap_mcp_result — the one place every proxy router in this package
turns an mealsight.agent.mcp_client.ToolCallResult into either real data
or a real HTTP error, so pantry/recipes/history/profile/grocery routers
each stay a thin call-and-translate layer with no MCP-error-shape
knowledge duplicated across them.

Two failure layers to translate, not one: ToolCallResult.success=False
is a TRANSPORT failure (the call never completed, even after
MCPClientManager's own retry) — reported as 502, this API's own fault
for depending on an upstream that didn't respond. result.data itself
being one of mealsight.mcp_servers.errors' structured shapes
(not_found/validation_error/internal_error) is a SUCCESSFUL call that
reports a business-level problem — not_found becomes 404,
validation_error becomes 400 (the caller's own fault), internal_error
becomes 502 (the tool ran but failed internally; still not the
caller's fault to fix).
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.mcp_client import ToolCallResult
from mealsight.api.errors import APIError


def unwrap_mcp_result(result: ToolCallResult) -> dict[str, Any]:
    if not result.success:
        raise APIError(502, "mcp_call_failed", result.error or "The MCP server call failed.")

    data = result.data
    if not isinstance(data, dict):
        return {"data": data}

    error = data.get("error")
    if error == "not_found":
        raise APIError(404, "not_found", data.get("message", "Not found."))
    if error == "validation_error":
        raise APIError(400, "validation_error", data.get("message", "Invalid input."))
    if error == "internal_error":
        raise APIError(502, "mcp_internal_error", data.get("message", "The MCP server failed internally."))

    return data
