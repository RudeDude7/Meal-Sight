"""Typed result shapes for the Recipe Engine tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from mealsight.matching.models import Importance

SubstitutionReason = Literal["unavailable", "allergic", "dietary", "dislike"]


class RecipeSummary(BaseModel):
    """A compact recipe listing — what search_recipes returns. No
    ingredient matching here; that's a separate call (mealsight.matching)."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    cuisine: str | None
    meal_type: str | None
    cook_time_minutes: int | None
    dietary_tags: list[str]


class SearchResults(BaseModel):
    """What search_recipes returns: the (possibly capped) list of
    summaries, plus total_matched — how many recipes satisfied every
    filter before the max_results cap was applied. A caller needs both:
    len(results) alone can't distinguish "there were only 3 matches" from
    "there were 200 matches and this is the first 3"."""

    model_config = ConfigDict(frozen=True)

    results: list[RecipeSummary]
    total_matched: int


class RecipeIngredient(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    quantity: float | None
    unit: str | None
    importance: Importance
    raw_measure: str | None


class RecipeDetail(BaseModel):
    """The full recipe, as returned by get_recipe."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    cuisine: str | None
    meal_type: str | None
    cook_time_minutes: int | None
    difficulty: str | None
    servings_base: int
    dietary_tags: list[str]
    ingredients: list[RecipeIngredient]
    steps: list[str]
    image_url: str | None


class ScaledIngredient(BaseModel):
    """One ingredient after scale_recipe has adjusted it — quantity_display
    is the human-readable, already-fraction-formatted string ("1/4", "1
    1/2", "2"), never a raw float."""

    model_config = ConfigDict(frozen=True)

    name: str
    quantity_display: str | None
    unit: str | None
    importance: Importance


class ScaledRecipe(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    original_servings: int
    target_servings: int
    scale_factor: float
    ingredients: list[ScaledIngredient]
    cook_time_minutes: int | None
    cook_time_adjusted: bool
    cook_time_note: str | None


class NutritionResult(BaseModel):
    """Per-serving nutrition totals for one recipe. Coverage is reported
    on every result — a total computed from partial data is always
    labeled as such, never presented as if it were complete."""

    model_config = ConfigDict(frozen=True)

    recipe_id: str
    servings: int
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sodium_mg: float
    ingredients_covered: int
    ingredients_total: int
    coverage_pct: float
    tags: list[str]
    coverage_note: str


class SubstitutionSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    substitute: str
    ratio: str
    flavor_impact: Literal["minimal", "noticeable", "significant"]
    notes: str | None


class SubstitutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient: str
    reason: SubstitutionReason
    suggestions: list[SubstitutionSuggestion]
    excluded_count: int
