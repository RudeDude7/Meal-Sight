"""A single, consistent error envelope for every error response this
API returns — {"code", "message", "trace_id"} — plus APIError, the one
exception every route in this package should raise for an expected,
named failure (a validation problem, a 404, an upstream MCP failure),
and register_error_handlers, which also converts FastAPI's own
RequestValidationError and any genuinely unexpected exception into the
identical shape. A raw traceback never reaches a client either way —
an unexpected exception is logged in full server-side (exc_info=True)
and reported to the caller as a generic "internal_error" message only.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mealsight.utils.logging import current_trace_id, get_logger

logger = get_logger("mealsight.api.errors")


class APIError(Exception):
    """Raise this for any expected, named API failure. status_code is a
    real HTTP status; code is the machine-readable identifier a client
    can branch on (e.g. "not_found", "validation_error",
    "rate_limited"); message is the human-readable explanation."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "trace_id": current_trace_id()}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _handle_api_error(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_envelope(exc.code, exc.message)
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_envelope("validation_error", str(exc.errors())),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", exc_info=True, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_envelope("internal_error", "An unexpected error occurred."),
        )
