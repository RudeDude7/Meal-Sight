"""validate_input — STUB (mealsight.agent.nodes._common.run_stub).

Will eventually confirm at least one of image_bytes/audio_bytes/
text_input was actually supplied, and reject empty/whitespace-only text
before perceive ever runs — mirroring the same "fail fast, before
spending an API call" discipline mealsight.perception.validation
already established for each individual modality, just applied once,
up front, across all three at once.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "validate_input"
DESCRIPTION = (
    "Will confirm at least one input modality (image, audio, or text) was actually provided."
)


async def validate_input(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
