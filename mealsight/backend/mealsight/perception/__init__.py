"""The Perception layer — plain Python tools that turn a fridge/pantry
photo, a voice memo, and/or typed text into structured signals, and
mealsight.perception.fusion.merge_perceptions, which combines up to all
three into one UnifiedMealRequest. Deterministic post-processing around
the (at most three) non-deterministic provider calls, all at
temperature=0.0; every analyze_* function never raises on failure — see
each one's own docstring in mealsight.perception.processor. No agent
wiring yet — these are called directly for now.
"""

from mealsight.perception.dietary import DIETARY_RESTRICTION_VOCABULARY, normalize_dietary_restriction
from mealsight.perception.fusion import merge_perceptions
from mealsight.perception.models import (
    AudioPerception,
    AvailableIngredient,
    Confidence,
    DetectedConflict,
    FreshnessAlert,
    IdentifiedItem,
    ModalityName,
    RawExtractedConstraints,
    RawIdentifiedItem,
    RawVisionPerception,
    TextPerception,
    UnifiedMealRequest,
    VisionPerception,
)
from mealsight.perception.processor import (
    analyze_fridge_photo,
    analyze_text_input,
    analyze_voice_memo,
    to_pantry_item_inputs,
)
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT, build_extraction_prompt
from mealsight.perception.validation import (
    MAX_AUDIO_FILE_SIZE_MB,
    MIN_IMAGE_DIMENSION_PX,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_IMAGE_FORMATS,
    AudioValidationError,
    ImageValidationError,
    TextValidationError,
    detect_audio_format,
    validate_audio,
    validate_image,
    validate_text,
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
    "AvailableIngredient",
    "Confidence",
    "DetectedConflict",
    "FreshnessAlert",
    "IdentifiedItem",
    "ImageValidationError",
    "ModalityName",
    "RawExtractedConstraints",
    "RawIdentifiedItem",
    "RawVisionPerception",
    "TextPerception",
    "TextValidationError",
    "UnifiedMealRequest",
    "VisionPerception",
    "analyze_fridge_photo",
    "analyze_text_input",
    "analyze_voice_memo",
    "build_extraction_prompt",
    "detect_audio_format",
    "merge_perceptions",
    "normalize_dietary_restriction",
    "to_pantry_item_inputs",
    "validate_audio",
    "validate_image",
    "validate_text",
]
