"""perceive — runs vision, audio, and text extraction for whichever
modalities validate_input found usable.

Concurrency, per the rate limiter: settings.VISION_MODEL (mistral-
medium-2505, analyze_fridge_photo) and settings.EXTRACTION_MODEL
(ministral-8b-2512, analyze_text_input) both call the Mistral account;
settings.AUDIO_MODEL (whisper-large-v3-turbo, analyze_voice_memo) calls
Groq, a completely separate account with its own rate limit. mealsight.
providers.rate_limiter.RateLimiter actually keys its token buckets per
MODEL id, not per provider, so vision and text extraction technically
already have independent buckets and wouldn't literally contend even
run concurrently — but they're still the same Mistral account behind
the same shared httpx connection pool, and the design instruction for
this node is to let Mistral work serialize naturally rather than run
it against itself. So vision and text are awaited one after another,
inside one coroutine; that whole sequential chain runs concurrently
(asyncio.gather) against Groq's independent audio transcription — the
one real, deliberate parallelism this node introduces.

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
"""

from __future__ import annotations

import asyncio
from typing import Any

from mealsight.agent.state import MealSightState
from mealsight.perception.models import AudioPerception, TextPerception, VisionPerception
from mealsight.perception.processor import analyze_fridge_photo, analyze_text_input, analyze_voice_memo
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.perceive")

NODE_NAME = "perceive"


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


async def _perceive_mistral_modalities(
    image_bytes: bytes | None, text_input: str | None
) -> tuple[VisionPerception | None, TextPerception | None, list[str]]:
    messages: list[str] = []
    vision_result: VisionPerception | None = None
    text_result: TextPerception | None = None

    if image_bytes:
        try:
            vision_result = await analyze_fridge_photo(image_bytes)
            messages.append(_vision_message(vision_result))
        except Exception:
            logger.error("perceive_vision_unexpected_failure", exc_info=True)
            messages.append(f"[{NODE_NAME}] Photo analysis failed unexpectedly — continuing without it.")

    # Awaited only after vision finishes — both are Mistral calls, kept
    # sequential relative to each other on purpose (see module docstring).
    if text_input and text_input.strip():
        try:
            text_result = await analyze_text_input(text_input)
            messages.append(_text_message(text_result))
        except Exception:
            logger.error("perceive_text_unexpected_failure", exc_info=True)
            messages.append(f"[{NODE_NAME}] Text analysis failed unexpectedly — continuing without it.")

    return vision_result, text_result, messages


async def _perceive_audio_modality(audio_bytes: bytes | None) -> tuple[AudioPerception | None, list[str]]:
    if not audio_bytes:
        return None, []
    try:
        audio_result = await analyze_voice_memo(audio_bytes)
        return audio_result, [_audio_message(audio_result)]
    except Exception:
        logger.error("perceive_audio_unexpected_failure", exc_info=True)
        return None, [f"[{NODE_NAME}] Voice memo analysis failed unexpectedly — continuing without it."]


async def perceive(state: MealSightState) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input from validate_input."]}

    image_bytes = state.get("image_bytes")
    audio_bytes = state.get("audio_bytes")
    text_input = state.get("text_input")

    (vision_result, text_result, mistral_messages), (audio_result, audio_messages) = await asyncio.gather(
        _perceive_mistral_modalities(image_bytes, text_input),
        _perceive_audio_modality(audio_bytes),
    )

    update: dict[str, Any] = {"stream_messages": [*mistral_messages, *audio_messages]}
    if vision_result is not None:
        update["vision_result"] = vision_result
    if audio_result is not None:
        update["audio_result"] = audio_result
    if text_result is not None:
        update["text_result"] = text_result

    logger.info("node_finished", node=NODE_NAME)
    return update
