"""Typed shapes for the vision perception layer.

Two schemas, deliberately not one: RawIdentifiedItem/RawVisionPerception
is what the model itself is asked to produce (mealsight.perception.
prompt) and what its JSON response is validated against — it has no
category field, because the model is never asked for one at all.
IdentifiedItem/VisionPerception is what analyze_fridge_photo actually
returns, with category filled in locally afterward (mealsight.pantry.
category.resolve_category) — see mealsight.perception.processor.
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
