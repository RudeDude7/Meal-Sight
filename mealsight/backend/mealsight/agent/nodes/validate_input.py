"""validate_input — confirms at least one input modality is both
present AND passes mealsight.perception.validation's own format/size
checks, before perceive ever spends a real API call on any of them.

Reuses the exact same validators every perception pipeline already
uses (validate_image/validate_audio/validate_text) rather than
reimplementing format/size checks here — this node's own job is only
to decide, across all three modalities at once, whether there's
anything worth running perception on at all.

Marks state terminal (with a plain-language reason) when none is —
every node after this one checks state.get("terminal") at its own
entry and skips its real work rather than running against genuinely
empty input (a per-node self-check; the graph's own edges stay
sequential regardless, see graph.py's own docstring).
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.state import MealSightState
from mealsight.perception.validation import (
    AudioValidationError,
    ImageValidationError,
    TextValidationError,
    validate_audio,
    validate_image,
    validate_text,
)
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.validate_input")

NODE_NAME = "validate_input"


async def validate_input(state: MealSightState) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    valid_modalities: list[str] = []
    problems: list[str] = []

    image_bytes = state.get("image_bytes")
    if image_bytes:
        try:
            validate_image(image_bytes)
            valid_modalities.append("photo")
        except ImageValidationError as exc:
            problems.append(f"photo ({exc})")

    audio_bytes = state.get("audio_bytes")
    if audio_bytes:
        try:
            validate_audio(audio_bytes)
            valid_modalities.append("voice memo")
        except AudioValidationError as exc:
            problems.append(f"voice memo ({exc})")

    text_input = state.get("text_input")
    if text_input and text_input.strip():
        try:
            validate_text(text_input)
            valid_modalities.append("typed message")
        except TextValidationError as exc:
            problems.append(f"typed message ({exc})")
    # Empty/whitespace-only text is deliberately NOT a validation
    # problem — it mirrors analyze_text_input's own "nothing was said"
    # short-circuit (phase 5.3): it simply isn't a modality that was
    # actually provided, so it contributes to neither list.

    if valid_modalities:
        message = f"Got usable input from your {' and '.join(valid_modalities)}."
        logger.info("node_finished", node=NODE_NAME, valid_modalities=valid_modalities)
        return {"stream_messages": [f"[{NODE_NAME}] {message}"]}

    reason = (
        "No input was provided at all."
        if not problems
        else "None of what you provided was usable: " + "; ".join(problems) + "."
    )
    logger.warning("node_finished", node=NODE_NAME, terminal=True, reason=reason)
    return {
        "terminal": True,
        "terminal_reason": reason,
        "stream_messages": [f"[{NODE_NAME}] {reason}"],
    }
