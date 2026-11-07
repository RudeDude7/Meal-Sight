"""analyze_fridge_photo / analyze_voice_memo / analyze_text_input — the
vision, audio, and text perception pipelines.

analyze_fridge_photo validates raw image bytes, calls the vision
provider with the benchmarked (and now quantity/unit/freshness-
extended) prompt, and post-processes every identified item into
pantry-ready shape. analyze_voice_memo validates raw audio bytes,
transcribes it (settings.AUDIO_MODEL), extracts structured cooking
constraints from the transcript (settings.EXTRACTION_MODEL), and
post-processes those constraints. analyze_text_input runs that exact
same extraction-plus-post-processing step directly on typed text —
same prompt, same schema, same _postprocess_constraints helper — since
typed text has no audio to transcribe first.

Deterministic post-processing throughout; the provider calls
themselves are the only non-deterministic steps, mitigated by
temperature=0.0 (mealsight.providers' own default for every call it
makes).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.avoid import implied_dietary_tags
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry.category import resolve_category
from mealsight.pantry.models import PantryItemInput
from mealsight.pantry.shelf_life import load_shelf_life_map
from mealsight.perception.dietary import normalize_dietary_restriction
from mealsight.perception.models import (
    AudioPerception,
    IdentifiedItem,
    RawExtractedConstraints,
    RawVisionPerception,
    TextPerception,
    VisionPerception,
)
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT, build_extraction_prompt
from mealsight.perception.restrictions import detect_dietary_restrictions
from mealsight.perception.validation import (
    AudioValidationError,
    ImageValidationError,
    TextValidationError,
    detect_audio_format,
    validate_audio,
    validate_image,
    validate_text,
)
from mealsight.providers import ProviderError, get_audio_provider, get_text_provider, get_vision_provider
from mealsight.providers.mistral import strip_code_fences
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.perception")

_AUDIO_FORMAT_TO_EXTENSION: dict[str, str] = {"WAV": "wav", "MP3": "mp3", "M4A": "m4a", "WEBM": "webm"}

# Graceful degradation (return an empty perception) is right for an
# occasional bad response and wrong for every response: a model that
# systematically returns something unparseable would otherwise look, from
# the outside, like a user who simply never sent a usable photo. After this
# many unparseable responses IN A ROW (any successful parse resets the
# count) the log line escalates from warning to error.
VISION_PARSE_FAILURE_ESCALATION_THRESHOLD = 3
RAW_RESPONSE_LOG_CHARS = 200
_consecutive_parse_failures = 0

_UNAVAILABLE_NOTE = "Vision analysis was unavailable — continuing without photo-derived pantry items."


def _empty_perception(note: str) -> VisionPerception:
    return VisionPerception(identified_items=[], total_items_found=0, photo_quality="unknown", notes=note)


def _parse_raw_response(text: str) -> RawVisionPerception:
    data = json.loads(strip_code_fences(text))
    return RawVisionPerception.model_validate(data)


def _record_parse_failure(raw_text: str, exc: Exception) -> None:
    global _consecutive_parse_failures
    _consecutive_parse_failures += 1
    head = raw_text[:RAW_RESPONSE_LOG_CHARS]
    logger.warning(
        "vision_response_unparseable",
        error=str(exc),
        raw_response_head=head,
        consecutive_failures=_consecutive_parse_failures,
    )
    if _consecutive_parse_failures >= VISION_PARSE_FAILURE_ESCALATION_THRESHOLD:
        logger.error(
            "vision_parsing_failing_systematically",
            consecutive_failures=_consecutive_parse_failures,
            model=settings.VISION_MODEL,
            raw_response_head=head,
        )


async def analyze_fridge_photo(
    image_bytes: bytes,
    pantry_db: Database | None = None,
    recipe_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> VisionPerception:
    """Identifies fridge/pantry contents from a photo, ready to hand
    straight to mealsight.pantry.update_pantry (see this module's own
    to_pantry_item_inputs).

    Validates image_bytes first — format, file size, minimum dimensions,
    all via mealsight.perception.validation.validate_image — and rejects
    clearly unusable input with a structured empty result, before ever
    spending a real API call on it.

    NEVER RAISES: a validation failure, a provider failure (rate limit,
    timeout, unavailable, an unparseable/invalid response), or any other
    unexpected error all return an empty VisionPerception
    (identified_items=[], total_items_found=0) with notes explaining
    what happened, rather than propagating an exception. This is
    deliberate — an agent combining this with audio and text input must
    be able to continue with whatever other input it has even when the
    vision step itself fails outright.

    Every returned item's category is derived locally, via mealsight.
    pantry.category.resolve_category — the model is never asked for a
    category at all (see mealsight.perception.prompt). Every item's
    name is normalized and canonicalized through the exact same
    normalize_ingredient + resolve_canonical pipeline every other part
    of this project uses, so an item reported here merges correctly
    with what update_pantry already has stored rather than creating a
    second row for a synonym of something already there. quantity/unit/
    freshness are passed through exactly as the model reported them —
    null stays null, never guessed at or defaulted to a plausible-
    looking value.
    """
    try:
        validate_image(image_bytes)
    except ImageValidationError as exc:
        logger.warning("vision_perception_image_rejected", reason=str(exc))
        return _empty_perception(str(exc))

    global _consecutive_parse_failures
    response_text = ""
    try:
        provider = get_vision_provider()
        response = await provider.analyze_image(image_bytes, VISION_PERCEPTION_PROMPT, settings.VISION_MODEL)
        response_text = response.text
        raw = _parse_raw_response(response_text)
        _consecutive_parse_failures = 0
    except ProviderError as exc:
        logger.warning("vision_perception_provider_failed", error=str(exc))
        return _empty_perception(_UNAVAILABLE_NOTE)
    except (json.JSONDecodeError, ValidationError) as exc:
        _record_parse_failure(response_text, exc)
        return _empty_perception(_UNAVAILABLE_NOTE)
    except Exception:
        logger.error("vision_perception_unexpected_failure", exc_info=True)
        return _empty_perception(_UNAVAILABLE_NOTE)

    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(recipe_db or get_recipe_db())
    shelf_life_map = await load_shelf_life_map(pantry_db)

    items: list[IdentifiedItem] = []
    for raw_item in raw.identified_items:
        canonical = resolve_canonical(normalize_ingredient(raw_item.name), synonym_map)
        category = resolve_category(canonical, shelf_life_map)
        items.append(
            IdentifiedItem(
                name=canonical,
                quantity=raw_item.quantity,
                unit=raw_item.unit,
                category=category,
                freshness=raw_item.freshness,
                confidence=raw_item.confidence,
            )
        )

    return VisionPerception(
        identified_items=items,
        total_items_found=len(items),
        photo_quality=raw.photo_quality,
        notes=raw.notes,
    )


def to_pantry_item_inputs(perception: VisionPerception) -> list[PantryItemInput]:
    """Converts a VisionPerception's identified_items into the exact
    input shape mealsight.pantry.update_pantry expects — this is what
    makes analyze_fridge_photo's output "directly consumable by
    update_pantry" concrete rather than aspirational. The one field
    rename: this schema's freshness becomes PantryItemInput's
    freshness_status, defaulting to PantryItemInput's own "fresh"
    default when the model reported no freshness observation at all —
    never guessed at here either."""
    inputs: list[PantryItemInput] = []
    for item in perception.identified_items:
        if item.freshness is None:
            observed = PantryItemInput(
                name=item.name, quantity=item.quantity, unit=item.unit, category=item.category
            )
        else:
            observed = PantryItemInput(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                category=item.category,
                freshness_status=item.freshness,
                freshness_observed=True,
            )
        inputs.append(observed)
    return inputs


_TRANSCRIPTION_UNAVAILABLE_NOTE = (
    "Transcription was unavailable — continuing without audio-derived constraints."
)
_EXTRACTION_UNAVAILABLE_NOTE = "Extraction was unavailable — continuing with the transcript only."


def _empty_audio_perception(note: str) -> AudioPerception:
    return AudioPerception(
        raw_transcript="",
        servings=None,
        max_cook_time_minutes=None,
        dietary_restrictions=[],
        cuisine_preference=None,
        avoid_ingredients=[],
        avoid_dishes=[],
        mood_or_preference=None,
        protein_preference=None,
        occasion=None,
        additional_context=note,
    )


def _transcript_only_perception(transcript: str, note: str) -> AudioPerception:
    return AudioPerception(
        raw_transcript=transcript,
        servings=None,
        max_cook_time_minutes=None,
        dietary_restrictions=[],
        cuisine_preference=None,
        avoid_ingredients=[],
        avoid_dishes=[],
        mood_or_preference=None,
        protein_preference=None,
        occasion=None,
        additional_context=note,
    )


def _append_note(existing: str | None, note: str) -> str:
    return f"{existing} {note}" if existing else note


def _postprocess_constraints(
    raw: RawExtractedConstraints, synonym_map: Mapping[str, str], utterance: str = ""
) -> tuple[list[str], list[str], str | None]:
    """Shared by analyze_voice_memo and analyze_text_input — the exact
    same code path post-processing a RawExtractedConstraints, regardless
    of whether it came from a transcript or typed text: avoid_
    ingredients canonicalized through normalize_ingredient + resolve_
    canonical, dietary_restrictions normalized onto DIETARY_RESTRICTION_
    VOCABULARY (an unrecognized phrase dropped from the list but
    preserved in the returned additional_context, never silently lost).
    Returns (canonical_avoid_ingredients, normalized_dietary_restrictions,
    additional_context)."""
    canonical_avoid_ingredients = [
        resolve_canonical(normalize_ingredient(name), synonym_map) for name in raw.avoid_ingredients
    ]

    normalized_dietary_restrictions: list[str] = []
    additional_context = raw.additional_context
    for phrase in raw.dietary_restrictions:
        normalized = normalize_dietary_restriction(phrase)
        if normalized is not None:
            if normalized not in normalized_dietary_restrictions:
                normalized_dietary_restrictions.append(normalized)
        else:
            additional_context = _append_note(
                additional_context, f'Unrecognized dietary phrasing not applied: "{phrase}".'
            )

    # Union with restrictions read straight from the user's words, and with
    # the diet an avoid list implies (avoiding every nut IS nut-free). The
    # model decides which field a restriction lands in and that choice varies
    # between near-identical sentences; the union means it cannot lose one.
    stated = detect_dietary_restrictions(utterance)
    for restriction in [*stated, *implied_dietary_tags(canonical_avoid_ingredients)]:
        if restriction not in normalized_dietary_restrictions:
            normalized_dietary_restrictions.append(restriction)

    return canonical_avoid_ingredients, normalized_dietary_restrictions, additional_context


def _canonical_on_hand(raw: RawExtractedConstraints, synonym_map: Mapping[str, str]) -> list[str]:
    """Ingredients the speaker said they have, canonicalized the same way
    avoid_ingredients are, de-duplicated, order kept."""
    names: list[str] = []
    for name in raw.ingredients_on_hand:
        canonical = resolve_canonical(normalize_ingredient(name), synonym_map)
        if canonical and canonical not in names:
            names.append(canonical)
    return names


async def analyze_voice_memo(
    audio_bytes: bytes,
    recipe_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> AudioPerception:
    """Transcribes a voice memo and extracts structured cooking
    constraints from it, in two separate steps — transcription
    (settings.AUDIO_MODEL, Groq Whisper) then extraction
    (settings.EXTRACTION_MODEL, via complete_json against
    RawExtractedConstraints) — because a failure in one has a different
    honest fallback than a failure in the other (see below).

    Validates audio_bytes first — format, file size, duration where
    determinable, all via mealsight.perception.validation.validate_audio
    — and rejects clearly unusable input with a structured empty result,
    before ever spending a real API call on it.

    NEVER RAISES, and distinguishes two different failure points rather
    than collapsing them into one generic fallback:
      - a validation or TRANSCRIPTION failure returns raw_transcript=""
        with every constraint field at its empty default and
        additional_context explaining what happened — there is no
        transcript to extract anything from at all.
      - an EXTRACTION failure, after transcription already succeeded,
        returns the real raw_transcript with every constraint field
        still at its empty default — the transcript itself is real,
        useful data even when structured extraction from it failed, so
        it's preserved rather than discarded along with the failed
        extraction.
    Either way, an agent combining this with vision and text input can
    always continue with whatever other input it has.

    avoid_ingredients is canonicalized through the exact same
    normalize_ingredient + resolve_canonical pipeline mealsight.
    perception.processor's own analyze_fridge_photo (and every other
    ingredient-touching part of this project) already uses.
    dietary_restrictions is normalized onto mealsight.perception.
    dietary.DIETARY_RESTRICTION_VOCABULARY — a phrase that doesn't map
    onto anything in that fixed vocabulary is dropped from dietary_
    restrictions (never guessed into the nearest-sounding entry) but
    preserved in additional_context, so it's never silently lost
    entirely.
    """
    try:
        validate_audio(audio_bytes)
    except AudioValidationError as exc:
        logger.warning("audio_perception_rejected", reason=str(exc))
        return _empty_audio_perception(str(exc))

    try:
        audio_provider = get_audio_provider()
        audio_format = detect_audio_format(audio_bytes)
        filename = f"memo.{_AUDIO_FORMAT_TO_EXTENSION[audio_format]}"
        transcription = await audio_provider.transcribe(audio_bytes, filename, settings.AUDIO_MODEL)
    except (ProviderError, AudioValidationError) as exc:
        logger.warning("audio_perception_transcription_failed", error=str(exc))
        return _empty_audio_perception(_TRANSCRIPTION_UNAVAILABLE_NOTE)
    except Exception:
        logger.error("audio_perception_transcription_unexpected_failure", exc_info=True)
        return _empty_audio_perception(_TRANSCRIPTION_UNAVAILABLE_NOTE)

    transcript = transcription.text

    try:
        text_provider = get_text_provider()
        raw = await text_provider.complete_json(
            build_extraction_prompt(transcript), RawExtractedConstraints, settings.EXTRACTION_MODEL
        )
    except ProviderError as exc:
        logger.warning("audio_perception_extraction_failed", error=str(exc))
        return _transcript_only_perception(transcript, _EXTRACTION_UNAVAILABLE_NOTE)
    except Exception:
        logger.error("audio_perception_extraction_unexpected_failure", exc_info=True)
        return _transcript_only_perception(transcript, _EXTRACTION_UNAVAILABLE_NOTE)

    if synonym_map is None:
        synonym_map = await load_synonym_map(recipe_db or get_recipe_db())

    canonical_avoid_ingredients, normalized_dietary_restrictions, additional_context = (
        _postprocess_constraints(raw, synonym_map, transcript)
    )

    return AudioPerception(
        raw_transcript=transcript,
        servings=raw.servings,
        max_cook_time_minutes=raw.max_cook_time_minutes,
        dietary_restrictions=normalized_dietary_restrictions,
        cuisine_preference=raw.cuisine_preference,
        avoid_ingredients=canonical_avoid_ingredients,
        avoid_dishes=raw.avoid_dishes,
        mood_or_preference=raw.mood_or_preference,
        protein_preference=raw.protein_preference,
        occasion=raw.occasion,
        additional_context=additional_context,
        ingredients_on_hand=_canonical_on_hand(raw, synonym_map),
    )


_TEXT_EXTRACTION_UNAVAILABLE_NOTE = (
    "Extraction was unavailable — continuing without text-derived constraints."
)


def _empty_text_perception(note: str) -> TextPerception:
    return TextPerception(
        servings=None,
        max_cook_time_minutes=None,
        dietary_restrictions=[],
        cuisine_preference=None,
        avoid_ingredients=[],
        avoid_dishes=[],
        mood_or_preference=None,
        protein_preference=None,
        occasion=None,
        additional_context=note,
    )


async def analyze_text_input(
    text: str,
    recipe_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> TextPerception:
    """Extracts structured cooking constraints directly from typed text
    — the same extraction step analyze_voice_memo runs on a transcript
    (identical prompt, identical RawExtractedConstraints schema,
    identical post-processing via this module's own
    _postprocess_constraints), just with no transcription stage first,
    since there's no audio to transcribe.

    Empty or whitespace-only text returns an empty result immediately,
    with NO API call spent on it at all — there's nothing for
    extraction to find in nothing, and asking a model to confirm that
    would just be spending a real call to learn what strip() already
    knows for free.

    Validates non-empty text against settings.max_text_length via
    mealsight.perception.validation.validate_text before spending a
    real extraction call on it.

    NEVER RAISES: empty input, a validation failure, or an extraction
    failure (ProviderError, or anything unexpected) all return an
    empty TextPerception with additional_context explaining what
    happened, the same graceful-degradation guarantee analyze_fridge_
    photo and analyze_voice_memo both already make.
    """
    if not text.strip():
        return _empty_text_perception("No text provided.")

    try:
        validate_text(text)
    except TextValidationError as exc:
        logger.warning("text_perception_rejected", reason=str(exc))
        return _empty_text_perception(str(exc))

    try:
        text_provider = get_text_provider()
        raw = await text_provider.complete_json(
            build_extraction_prompt(text), RawExtractedConstraints, settings.EXTRACTION_MODEL
        )
    except ProviderError as exc:
        logger.warning("text_perception_extraction_failed", error=str(exc))
        return _empty_text_perception(_TEXT_EXTRACTION_UNAVAILABLE_NOTE)
    except Exception:
        logger.error("text_perception_extraction_unexpected_failure", exc_info=True)
        return _empty_text_perception(_TEXT_EXTRACTION_UNAVAILABLE_NOTE)

    if synonym_map is None:
        synonym_map = await load_synonym_map(recipe_db or get_recipe_db())

    canonical_avoid_ingredients, normalized_dietary_restrictions, additional_context = (
        _postprocess_constraints(raw, synonym_map, text)
    )

    return TextPerception(
        servings=raw.servings,
        max_cook_time_minutes=raw.max_cook_time_minutes,
        dietary_restrictions=normalized_dietary_restrictions,
        cuisine_preference=raw.cuisine_preference,
        avoid_ingredients=canonical_avoid_ingredients,
        avoid_dishes=raw.avoid_dishes,
        mood_or_preference=raw.mood_or_preference,
        protein_preference=raw.protein_preference,
        occasion=raw.occasion,
        additional_context=additional_context,
        ingredients_on_hand=_canonical_on_hand(raw, synonym_map),
    )
