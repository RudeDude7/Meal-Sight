"""The Vision Perception layer — plain Python tools that turn a fridge/
pantry photo into structured, pantry-ready items. Deterministic
post-processing around one non-deterministic vision API call
(temperature=0.0), never raises on failure — see
mealsight.perception.processor.analyze_fridge_photo's own docstring.
No agent wiring yet — these are called directly for now.
"""

from mealsight.perception.dietary import DIETARY_RESTRICTION_VOCABULARY, normalize_dietary_restriction
from mealsight.perception.models import (
    AudioPerception,
    Confidence,
    IdentifiedItem,
    RawExtractedConstraints,
    RawIdentifiedItem,
    RawVisionPerception,
    VisionPerception,
)
from mealsight.perception.processor import analyze_fridge_photo, analyze_voice_memo, to_pantry_item_inputs
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT, build_extraction_prompt
from mealsight.perception.validation import (
    MAX_AUDIO_FILE_SIZE_MB,
    MIN_IMAGE_DIMENSION_PX,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_IMAGE_FORMATS,
    AudioValidationError,
    ImageValidationError,
    detect_audio_format,
    validate_audio,
    validate_image,
)

__all__ = [
    "DIETARY_RESTRICTION_VOCABULARY",
    "MAX_AUDIO_FILE_SIZE_MB",
    "MIN_IMAGE_DIMENSION_PX",
    "SUPPORTED_AUDIO_FORMATS",
    "SUPPORTED_IMAGE_FORMATS",
    "VISION_PERCEPTION_PROMPT",
    "AudioPerception",
    "AudioValidationError",
    "Confidence",
    "IdentifiedItem",
    "ImageValidationError",
    "RawExtractedConstraints",
    "RawIdentifiedItem",
    "RawVisionPerception",
    "VisionPerception",
    "analyze_fridge_photo",
    "analyze_voice_memo",
    "build_extraction_prompt",
    "detect_audio_format",
    "normalize_dietary_restriction",
    "to_pantry_item_inputs",
    "validate_audio",
    "validate_image",
]
