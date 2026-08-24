"""Typed result shapes for the ingredient matcher. MatchResult is what the
agent's reasoning prompt (a later phase) actually consumes — compact,
self-explanatory, and JSON-serializable via pydantic's own model_dump."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Importance = Literal["critical", "important", "optional"]
FlavorImpact = Literal["minimal", "noticeable", "significant"]


class MatchedItem(BaseModel):
    """A recipe ingredient the pantry has an exact canonical match for."""

    model_config = ConfigDict(frozen=True)

    name: str
    importance: Importance


class SubstitutableItem(BaseModel):
    """A recipe ingredient the pantry doesn't have directly, but for which
    the pantry has an eligible substitute on hand."""

    model_config = ConfigDict(frozen=True)

    original: str
    substitute: str
    ratio: str
    flavor_impact: FlavorImpact
    importance: Importance


class MissingItem(BaseModel):
    """A recipe ingredient with neither a direct match nor an eligible,
    available substitute."""

    model_config = ConfigDict(frozen=True)

    name: str
    importance: Importance


class PartialMatchItem(BaseModel):
    """A recipe ingredient the pantry only has a less specific form of —
    the recipe wants a particular cut/variety (e.g. "chicken thighs") and
    the pantry only has the generic ingredient ("chicken"). Scored at
    settings.substitution_match_weight, same as a table-driven
    substitution, since it's the same degree of "not quite what was
    asked for" — but it's not a swap for a different ingredient, so it's
    kept in its own list rather than folded into substitutable_items."""

    model_config = ConfigDict(frozen=True)

    name: str
    pantry_match: str
    importance: Importance
    note: str


class MatchResult(BaseModel):
    """The full result of matching one recipe against one pantry."""

    model_config = ConfigDict(frozen=True)

    match_score: float
    can_cook: bool
    matched_items: list[MatchedItem]
    substitutable_items: list[SubstitutableItem]
    partial_matches: list[PartialMatchItem]
    missing_items: list[MissingItem]
    critical_missing: list[str]
    summary: str
