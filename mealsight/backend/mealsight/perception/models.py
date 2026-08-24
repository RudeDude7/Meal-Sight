"""Typed shapes for the vision and audio perception layers.

Both follow the identical two-schema split: a Raw* shape is what a
model is actually asked to produce and validated against, and the
final shape is what analyze_fridge_photo / analyze_voice_memo actually
return, with everything that's derived or normalized locally (never
by the model) filled in afterward.

RawIdentifiedItem/RawVisionPerception is what the vision model itself
produces — no category field, because the model is never asked for one
at all. IdentifiedItem/VisionPerception is what analyze_fridge_photo
returns, with category filled in locally (mealsight.pantry.category.
resolve_category) — see mealsight.perception.processor.

RawExtractedConstraints is what the text extraction model produces from
a transcript — dietary_restrictions and avoid_ingredients both still in
whatever loose phrasing the model used. AudioPerception is what
analyze_voice_memo returns: raw_transcript added, dietary_restrictions
normalized to DIETARY_RESTRICTION_VOCABULARY, and avoid_ingredients
canonicalized through mealsight.matching — see mealsight.perception.
processor.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Confidence = Literal["high", "medium", "low"]


class RawIdentifiedItem(BaseModel):
    """One item exactly as the model reports it — name, quantity, unit,
    freshness, and confidence, never category."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None = None
    unit: str | None = None
    freshness: str | None = None
    confidence: Confidence


class RawVisionPerception(BaseModel):
    """The model's raw JSON response, before category is derived
    locally and every name is normalized/canonicalized."""

    model_config = ConfigDict(frozen=True)

    identified_items: list[RawIdentifiedItem]
    total_items_found: int
    photo_quality: str
    notes: str | None = None


class IdentifiedItem(BaseModel):
    """One post-processed item: name normalized and canonicalized
    through mealsight.matching, category derived locally (never from
    the model), quantity/unit/freshness passed through unchanged from
    what the model reported — null stays null, never guessed at."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None
    unit: str | None
    category: str
    freshness: str | None
    confidence: Confidence


class VisionPerception(BaseModel):
    """What analyze_fridge_photo returns. An empty identified_items list
    with total_items_found=0 is a normal, valid result — both when the
    model genuinely found nothing, and (see mealsight.perception.
    processor's graceful-degradation path) when the photo was rejected
    or the provider call failed; notes explains which."""

    model_config = ConfigDict(frozen=True)

    identified_items: list[IdentifiedItem]
    total_items_found: int
    photo_quality: str
    notes: str | None


class RawExtractedConstraints(BaseModel):
    """What the extraction model (settings.EXTRACTION_MODEL) is asked to
    produce from a transcript — every field but is optional, since a
    real voice memo typically states only some of these. dietary_
    restrictions and avoid_ingredients are still in whatever loose
    phrasing the model used; normalization/canonicalization happens
    afterward, never here."""

    model_config = ConfigDict(frozen=True)

    servings: int | None = None
    max_cook_time_minutes: int | None = None
    dietary_restrictions: list[str] = []
    cuisine_preference: str | None = None
    avoid_ingredients: list[str] = []
    avoid_dishes: list[str] = []
    mood_or_preference: str | None = None
    protein_preference: str | None = None
    occasion: str | None = None
    additional_context: str | None = None


class AudioPerception(BaseModel):
    """What analyze_voice_memo returns. raw_transcript is the only field
    that's never empty on a genuine success — every other field is null
    or an empty list when the memo simply never mentioned it, which is
    the normal, expected case for most fields on most memos, not a
    failure signal.

    On graceful degradation (mealsight.perception.processor's own
    never-raises guarantee): a transcription failure returns
    raw_transcript="" with every constraint field at its empty default;
    an extraction failure on an otherwise-successful transcript returns
    the real raw_transcript with every constraint field still at its
    empty default. additional_context carries the explanatory note for
    either case — the same role VisionPerception.notes plays, reusing
    this schema's own existing free-text field rather than adding one
    beyond what this phase's task actually specified."""

    model_config = ConfigDict(frozen=True)

    raw_transcript: str
    servings: int | None
    max_cook_time_minutes: int | None
    dietary_restrictions: list[str]
    cuisine_preference: str | None
    avoid_ingredients: list[str]
    avoid_dishes: list[str]
    mood_or_preference: str | None
    protein_preference: str | None
    occasion: str | None
    additional_context: str | None
