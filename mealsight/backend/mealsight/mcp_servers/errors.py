"""Structured error result shapes shared by every MCP server in this
package — not_found_error, validation_error, internal_error. Originally
lived only in mealsight.mcp_servers.recipe_engine.serialization; moved
here once a second server (pantry_manager) needed the identical shapes,
so an agent talking to either server sees exactly the same error
vocabulary rather than two servers each with their own slightly
different dialect of "this went wrong."
"""

from __future__ import annotations

from typing import Any


def not_found_error(entity: str, entity_id: str) -> dict[str, Any]:
    """A structured "doesn't exist" result — never an exception — naming
    both what kind of thing was looked up and the exact id that failed."""
    return {
        "error": "not_found",
        "message": f"No {entity} found with id {entity_id!r}.",
        entity + "_id": entity_id,
    }


def validation_error(parameter: str, message: str, accepted: list[str] | None = None) -> dict[str, Any]:
    """A structured "bad input" result, naming the offending parameter
    and (when it's an enum-like choice) the accepted values."""
    error: dict[str, Any] = {"error": "validation_error", "parameter": parameter, "message": message}
    if accepted is not None:
        error["accepted_values"] = accepted
    return error


def internal_error(
    message: str = "An unexpected error occurred while processing this request.",
) -> dict[str, Any]:
    """A structured failure result for anything unexpected — deliberately
    generic. The real exception is logged server-side (in each server's
    own server.py); it never reaches the caller, so nothing internal
    ever leaks into an agent's context."""
    return {"error": "internal_error", "message": message}
