"""POST /api/recommend and GET /api/recommend/{session_id} — start a
recommendation as a background task and let the caller poll for it,
which is what makes this API usable before the next session's WebSocket
streaming exists at all.

Validation reuses mealsight.perception.validation's own validate_image/
validate_audio/validate_text directly — the exact same checks perceive
(agent node 2) already runs before ever spending a real provider call,
so a bad upload is rejected here, at the API boundary, before an agent
run even starts, not duplicated as a second, parallel set of rules that
could quietly drift from the first.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request, UploadFile
from pydantic import BaseModel

from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.runner import run_recommendation
from mealsight.agent.state import MealSightState
from mealsight.api.dependencies import MCPManagerDep, RateLimiterDep, SessionsDep
from mealsight.api.errors import APIError
from mealsight.api.sessions import RecommendationSession, SessionStore
from mealsight.config.settings import settings
from mealsight.perception.validation import (
    AudioValidationError,
    ImageValidationError,
    TextValidationError,
    validate_audio,
    validate_image,
    validate_text,
)
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.api.recommend")

router = APIRouter(prefix="/api/recommend", tags=["recommend"])

# Every field the request also carries a real max size for locally
# (max_image_size_mb, the audio validator's own 25MB Groq limit, and
# max_text_length) — this is the CONTENT-LENGTH gate checked before any
# of the body is actually read into memory, deliberately looser than
# the sum of those individual limits (form-encoding overhead, field
# boundaries) so a genuinely oversized upload is still rejected before
# ever touching request.form(), without the gate itself being so tight
# it rejects a legitimate, fully within-limits multipart body.
_MAX_AUDIO_MB = 25
MAX_REQUEST_BYTES = int((settings.max_image_size_mb + _MAX_AUDIO_MB + 1) * 1024 * 1024)

# Public fields of MealSightState a client should actually see — never
# the raw perception objects (VisionPerception etc.), which aren't
# JSON-serializable and were never meant to leave the graph.
_RESULT_FIELDS = (
    "final_response",
    "top_recommendation",
    "scaled_recipe",
    "grocery_list",
    "nutrition_info",
    "processing_trace",
    "stream_messages",
    "matched_ingredients",
)


class RecommendationAccepted(BaseModel):
    session_id: str
    status: str
    websocket_url: str


def _reject_oversized(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_REQUEST_BYTES:
        raise APIError(
            413,
            "payload_too_large",
            f"Request body is {int(content_length) / (1024 * 1024):.1f}MB, over the "
            f"{MAX_REQUEST_BYTES / (1024 * 1024):.0f}MB limit.",
        )


def _serialize_result(final_state: MealSightState) -> dict[str, object]:
    result = {field: final_state[field] for field in _RESULT_FIELDS if field in final_state}  # type: ignore[literal-required]
    top_recommendation = final_state.get("top_recommendation")
    if top_recommendation is not None and top_recommendation.get("available"):
        # Flattened here (rather than making the frontend reach into
        # top_recommendation itself) specifically so mealsight.api.
        # routers.cook has one obvious, stable field to read recipe_id
        # from — the same reason matched_ingredients (above) is its own
        # top-level field rather than nested inside scaled_recipe.
        result["recipe_id"] = top_recommendation.get("recipe_id")
    return result


async def _run_in_background(
    session_id: str,
    manager: MCPClientManager,
    sessions: SessionStore,
    image_bytes: bytes | None,
    audio_bytes: bytes | None,
    text_input: str | None,
) -> None:
    session = sessions.get(session_id)
    stream = session.stream if session is not None else None
    sessions.mark_running(session_id, session_id)
    try:
        final_state = await run_recommendation(
            image_bytes=image_bytes,
            audio_bytes=audio_bytes,
            text_input=text_input,
            manager=manager,
            trace_id=session_id,
            stream=stream,
        )
        result = _serialize_result(final_state)
        sessions.mark_complete(session_id, result)
        if stream is not None:
            stream.emit("complete", result=result)
    except Exception:
        logger.error("recommend_background_task_failed", exc_info=True, session_id=session_id)
        error_message = "The recommendation failed unexpectedly."
        sessions.mark_failed(session_id, error_message)
        if stream is not None:
            stream.emit("error", code="internal_error", message=error_message)


@router.post("", status_code=202, response_model=RecommendationAccepted)
async def start_recommendation(
    request: Request,
    manager: MCPManagerDep,
    sessions: SessionsDep,
    rate_limiter: RateLimiterDep,
    text: str | None = Form(default=None),
    image: UploadFile | None = None,
    audio: UploadFile | None = None,
) -> RecommendationAccepted:
    _reject_oversized(request)

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.check(client_ip):
        raise APIError(
            429,
            "rate_limited",
            f"Too many recommendations submitted — limit is "
            f"{settings.max_submissions_per_minute} per minute per client.",
        )

    image_bytes = await image.read() if image is not None else None
    audio_bytes = await audio.read() if audio is not None else None
    text_input = text if text and text.strip() else None

    if image_bytes:
        try:
            validate_image(image_bytes)
        except ImageValidationError as exc:
            raise APIError(400, "invalid_image", str(exc)) from exc
    if audio_bytes:
        try:
            validate_audio(audio_bytes)
        except AudioValidationError as exc:
            raise APIError(400, "invalid_audio", str(exc)) from exc
    if text_input:
        try:
            validate_text(text_input)
        except TextValidationError as exc:
            raise APIError(400, "invalid_text", str(exc)) from exc

    if not image_bytes and not audio_bytes and not text_input:
        raise APIError(
            400, "no_input_provided", "Provide at least one of image, audio, or text."
        )

    session = sessions.create()

    asyncio.create_task(
        _run_in_background(session.session_id, manager, sessions, image_bytes, audio_bytes, text_input)
    )

    return RecommendationAccepted(
        session_id=session.session_id,
        status=session.status,
        websocket_url=f"/ws/{session.session_id}",
    )


@router.get("/{session_id}")
async def get_recommendation(session_id: str, sessions: SessionsDep) -> dict[str, object]:
    session: RecommendationSession | None = sessions.get(session_id)
    if session is None:
        raise APIError(404, "not_found", f"No recommendation session found with id {session_id!r}.")

    body: dict[str, object] = {"session_id": session.session_id, "status": session.status}
    if session.result is not None:
        body["result"] = session.result
    if session.error is not None:
        body["error"] = session.error
    return body
