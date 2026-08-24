"""perceive — STUB (mealsight.agent.nodes._common.run_stub).

Will call mealsight.perception's analyze_fridge_photo / analyze_voice_
memo / analyze_text_input concurrently, one per input modality actually
present on state, writing each result to vision_result/audio_result/
text_result. Every one of those three functions already never raises
(phase 5.1-5.3's own graceful-degradation guarantee), so this node's
real job is orchestration — running the ones that apply concurrently,
not sequentially — not error handling of its own.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "perceive"
DESCRIPTION = (
    "Will run analyze_fridge_photo/analyze_voice_memo/analyze_text_input concurrently "
    "for whichever modalities were provided."
)


async def perceive(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
