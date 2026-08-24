"""The Vision Perception layer — plain Python tools that turn a fridge/
pantry photo into structured, pantry-ready items. Deterministic
post-processing around one non-deterministic vision API call
(temperature=0.0), never raises on failure — see
mealsight.perception.processor.analyze_fridge_photo's own docstring.
No agent wiring yet — these are called directly for now.
"""

from mealsight.perception.models import (
    Confidence,
    IdentifiedItem,
    RawIdentifiedItem,
    RawVisionPerception,
    VisionPerception,
)
from mealsight.perception.processor import analyze_fridge_photo, to_pantry_item_inputs
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT
from mealsight.perception.validation import (
    MIN_IMAGE_DIMENSION_PX,
    SUPPORTED_IMAGE_FORMATS,
    ImageValidationError,
    validate_image,
)

__all__ = [
    "MIN_IMAGE_DIMENSION_PX",
    "SUPPORTED_IMAGE_FORMATS",
    "VISION_PERCEPTION_PROMPT",
    "Confidence",
    "IdentifiedItem",
    "ImageValidationError",
    "RawIdentifiedItem",
    "RawVisionPerception",
    "VisionPerception",
    "analyze_fridge_photo",
    "to_pantry_item_inputs",
    "validate_image",
]
