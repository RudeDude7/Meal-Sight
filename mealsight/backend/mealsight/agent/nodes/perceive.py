"""perceive — runs vision, audio, and text extraction for whichever
modalities validate_input found usable.

Granularity: this node alone is roughly 12 of a real ~13-second
recommendation (real Mistral vision + text calls, a real Groq audio
call) — by far the longest single wait in the whole graph, and the
graph-level node_start/node_complete events every node gets from
_timed (mealsight.agent.graph) only bracket the WHOLE node, saying
nothing for the entire duration in between. So this node emits its own
"ingredient_found" progress events throughout — not from a fixed
vocabulary invented for this (ingredient_found is the closest fit among
the eight message types this phase defines; every one of the events
below, for all three modalities, uses it, each tagged with its own
modality field) — at three distinct moments per modality, not only the
one moment the previous phase covered:

  1. the instant a modality's own provider call is ABOUT to start
     ("Analyzing your photo...") — fired before the await, so a
     listening client knows work has begun immediately, not 5-14
     real seconds later when the first result happens to arrive.
  2. a periodic heartbeat (_run_with_heartbeat, every
     HEARTBEAT_INTERVAL_SECONDS) while that call is still in flight —
     cycling through a small set of genuinely varied, honest messages
     per modality rather than repeating one identical string or
     fabricating a fake percentage this node has no real way to
     compute; a call that finishes before the first interval elapses
     (the common case for text extraction, and often audio) never
     triggers one at all.
  3. completion (or a caught failure) — unchanged from before.

CONCURRENCY: all three modalities now run fully concurrently
(asyncio.gather across all three, not just audio-against-Mistral).
Previously vision and text were deliberately kept sequential relative
to each other despite both hitting the same Mistral account, reasoning
that they were "still the same account behind the same shared httpx
connection pool." Reopened this phase specifically because the actual
constraint that would matter — mealsight.providers.rate_limiter.
RateLimiter — was already known (phase 6.2) to key its buckets, and its
lock, per MODEL id, not per provider: settings.VISION_MODEL (mistral-
medium-2505) and settings.EXTRACTION_MODEL (ministral-8b-2512) are two
different keys with two entirely independent buckets and two
independent asyncio.Locks, so they never contend no matter how they're
scheduled. There was no remaining reason to keep them sequential, and
doing so was actively costing real wall-clock time (a real vision call
alone is 8-9s; running text after it added its own ~1s on top, for a
resource the two calls were never actually going to fight over).
Verified directly (see this node's own tests) that all three now
overlap in real wall-clock time, and separately, that the rate limiter
still enforces each model's own budget correctly under this concurrency
— no 429s, no cross-model bleed — before treating this as safe to ship.

Each modality is wrapped in its own try/except, on top of the fact
that analyze_fridge_photo/analyze_voice_memo/analyze_text_input already
never raise on their own (phase 5.1-5.3's own graceful-degradation
guarantee) — this node's own contract is "never raise" too, for
anything, including a genuinely unexpected bug in this node's own code,
not just the failure modes perception already knows how to degrade
around. One modality failing here never prevents the others: each is
independent, and a caught failure here simply means that modality's
own state field is left unset, exactly the "may fail and leave its
field unset" contract MealSightState's own docstring describes.

Only the FINAL message per modality (completion or failure) is added to
state["stream_messages"], exactly as before — the start/heartbeat
events go through runtime.context.stream only, never the state
accumulator, so every existing "one message per attempted modality"
assumption a non-streaming caller (or an existing test) already made
about stream_messages' own length stays true unchanged.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable
from typing import Any, TypeVar

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext, StreamSink
from mealsight.agent.state import MealSightState
from mealsight.perception.models import AudioPerception, TextPerception, VisionPerception
from mealsight.perception.processor import analyze_fridge_photo, analyze_text_input, analyze_voice_memo
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.perceive")

NODE_NAME = "perceive"

# How often a heartbeat fires for a modality still in flight. Chosen to
# comfortably undercut the real vision call's own observed 8-9s
# duration — no gap longer than this should ever go by without SOME
# progress signal, for any modality.
HEARTBEAT_INTERVAL_SECONDS = 3.0

T = TypeVar("T")

_START_MESSAGES: dict[str, str] = {
    "vision": f"[{NODE_NAME}] Analyzing your photo...",
    "audio": f"[{NODE_NAME}] Transcribing your voice memo...",
    "text": f"[{NODE_NAME}] Reading your request...",
}

# Varied and honest, not a fake progress bar: each modality cycles
# through its own small set of real, non-repeating descriptions of what
# is genuinely still happening, in order, wrapping around for a call
# that runs long enough to need more heartbeats than a modality has its
# own distinct messages.
_HEARTBEAT_MESSAGES: dict[str, tuple[str, ...]] = {
    "vision": (
        f"[{NODE_NAME}] Still analyzing your photo — a full fridge takes a few extra seconds "
        "to identify item by item.",
        f"[{NODE_NAME}] Still working through the photo...",
        f"[{NODE_NAME}] The vision model is still looking closely at what's in the photo.",
    ),
    "audio": (
        f"[{NODE_NAME}] Still transcribing your voice memo...",
        f"[{NODE_NAME}] Still working through the audio...",
    ),
    "text": (f"[{NODE_NAME}] Still reading your request...",),
}


def _vision_message(result: VisionPerception) -> str:
    if result.total_items_found > 0:
        return f"[{NODE_NAME}] Found {result.total_items_found} item(s) in your photo."
    return f"[{NODE_NAME}] Couldn't identify anything in the photo ({result.notes or 'no items found'})."


def _audio_message(result: AudioPerception) -> str:
    if result.raw_transcript.strip():
        return f'[{NODE_NAME}] Heard: "{result.raw_transcript.strip()}"'
    context = result.additional_context or "no transcript"
    return f"[{NODE_NAME}] Couldn't get anything from the voice memo ({context})."


def _text_stated_anything(result: TextPerception) -> bool:
    return any(
        [
            result.servings is not None,
            result.max_cook_time_minutes is not None,
            result.dietary_restrictions,
            result.cuisine_preference is not None,
            result.avoid_ingredients,
            result.avoid_dishes,
            result.mood_or_preference is not None,
            result.protein_preference is not None,
            result.occasion is not None,
        ]
    )


def _text_message(result: TextPerception) -> str:
    if _text_stated_anything(result):
        return f"[{NODE_NAME}] Understood your typed request."
    context = result.additional_context or "no constraints stated"
    return f"[{NODE_NAME}] Nothing specific found in your typed request ({context})."


def _emit(stream: StreamSink | None, modality: str, message: str) -> None:
    if stream is not None:
        stream.emit("ingredient_found", modality=modality, message=message)


async def _run_with_heartbeat(modality: str, stream: StreamSink | None, awaitable: Awaitable[T]) -> T:
    """Runs awaitable to completion, emitting a periodic heartbeat every
    HEARTBEAT_INTERVAL_SECONDS while it's still in flight. asyncio.wait
    with a timeout only ever PEEKS at whether the task has finished — it
    never cancels or otherwise interferes with it, so this changes
    nothing about the real call's own behavior, only how often this
    function reports back while waiting."""
    task: asyncio.Task[T] = asyncio.ensure_future(awaitable)
    heartbeat_texts = itertools.cycle(_HEARTBEAT_MESSAGES[modality])
    while True:
        done, _pending = await asyncio.wait({task}, timeout=HEARTBEAT_INTERVAL_SECONDS)
        if task in done:
            return await task
        _emit(stream, modality, next(heartbeat_texts))


async def _run_vision(
    image_bytes: bytes | None, stream: StreamSink | None
) -> tuple[VisionPerception | None, str | None]:
    if not image_bytes:
        return None, None
    _emit(stream, "vision", _START_MESSAGES["vision"])
    try:
        vision_result = await _run_with_heartbeat("vision", stream, analyze_fridge_photo(image_bytes))
        message = _vision_message(vision_result)
        _emit(stream, "vision", message)
        return vision_result, message
    except Exception:
        logger.error("perceive_vision_unexpected_failure", exc_info=True)
        message = f"[{NODE_NAME}] Photo analysis failed unexpectedly — continuing without it."
        _emit(stream, "vision", message)
        return None, message


async def _run_audio(
    audio_bytes: bytes | None, stream: StreamSink | None
) -> tuple[AudioPerception | None, str | None]:
    if not audio_bytes:
        return None, None
    _emit(stream, "audio", _START_MESSAGES["audio"])
    try:
        audio_result = await _run_with_heartbeat("audio", stream, analyze_voice_memo(audio_bytes))
        message = _audio_message(audio_result)
        _emit(stream, "audio", message)
        return audio_result, message
    except Exception:
        logger.error("perceive_audio_unexpected_failure", exc_info=True)
        message = f"[{NODE_NAME}] Voice memo analysis failed unexpectedly — continuing without it."
        _emit(stream, "audio", message)
        return None, message


async def _run_text(
    text_input: str | None, stream: StreamSink | None
) -> tuple[TextPerception | None, str | None]:
    if not text_input or not text_input.strip():
        return None, None
    _emit(stream, "text", _START_MESSAGES["text"])
    try:
        text_result = await _run_with_heartbeat("text", stream, analyze_text_input(text_input))
        message = _text_message(text_result)
        _emit(stream, "text", message)
        return text_result, message
    except Exception:
        logger.error("perceive_text_unexpected_failure", exc_info=True)
        message = f"[{NODE_NAME}] Text analysis failed unexpectedly — continuing without it."
        _emit(stream, "text", message)
        return None, message


async def perceive(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input from validate_input."]}

    image_bytes = state.get("image_bytes")
    audio_bytes = state.get("audio_bytes")
    text_input = state.get("text_input")
    stream = runtime.context.stream if runtime.context is not None else None

    (vision_result, vision_message), (audio_result, audio_message), (text_result, text_message) = (
        await asyncio.gather(
            _run_vision(image_bytes, stream),
            _run_audio(audio_bytes, stream),
            _run_text(text_input, stream),
        )
    )

    update: dict[str, Any] = {
        "stream_messages": [m for m in (vision_message, text_message, audio_message) if m is not None]
    }
    if vision_result is not None:
        update["vision_result"] = vision_result
    if audio_result is not None:
        update["audio_result"] = audio_result
    if text_result is not None:
        update["text_result"] = text_result

    logger.info("node_finished", node=NODE_NAME)
    return update
