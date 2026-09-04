// Mirrors mealsight/recipe_engine/models.py.

import type { Importance } from '@/types/matching'

export type SubstitutionReason = 'unavailable' | 'allergic' | 'dietary' | 'dislike'

/** A compact recipe listing — what GET /api/recipes/search returns per result. */
export interface RecipeSummary {
  id: string
  name: string
  cuisine: string | null
  meal_type: string | null
  cook_time_minutes: number | null
  dietary_tags: string[]
}

export interface SearchResults {
  results: RecipeSummary[]
  /** How many recipes matched before max_results capped the list. */
  total_matched: number
}

export interface RecipeIngredient {
  name: string
  quantity: number | null
  unit: string | null
  importance: Importance
  raw_measure: string | null
}

/** The full recipe, as returned by GET /api/recipes/{id}. */
export interface RecipeDetail {
  id: string
  name: string
  cuisine: string | null
  meal_type: string | null
  cook_time_minutes: number | null
  difficulty: string | null
  servings_base: number
  dietary_tags: string[]
  ingredients: RecipeIngredient[]
  steps: string[]
  image_url: string | null
}

/**
 * One ingredient after scaling — quantity_display is always a
 * human-readable, already-fraction-formatted string ("1/4", "1 1/2"),
 * never a raw number.
 */
export interface ScaledIngredient {
  name: string
  quantity_display: string | null
  unit: string | null
  importance: Importance
}

export interface ScaledRecipe {
  id: string
  name: string
  original_servings: number
  target_servings: number
  scale_factor: number
  ingredients: ScaledIngredient[]
  cook_time_minutes: number | null
  cook_time_adjusted: boolean
  cook_time_note: string | null
}

/**
 * Per-serving nutrition totals. coverage_pct/coverage_note are always
 * present — a total computed from partial ingredient data is always
 * labeled as such, never presented as complete.
 */
export interface NutritionResult {
  recipe_id: string
  servings: number
  calories: number
  protein_g: number
  carbs_g: number
  fat_g: number
  fiber_g: number
  sodium_mg: number
  ingredients_covered: number
  ingredients_total: number
  coverage_pct: number
  tags: string[]
  coverage_note: string
}

export interface SubstitutionSuggestion {
  substitute: string
  ratio: string
  flavor_impact: 'minimal' | 'noticeable' | 'significant'
  notes: string | null
}

export interface SubstitutionResult {
  ingredient: string
  reason: SubstitutionReason
  suggestions: SubstitutionSuggestion[]
  excluded_count: number
}

/**
 * One GET /api/recipes/by-ingredients result. match_percentage is the
 * fraction of the SUPPLIED ingredient list this recipe uses — not the
 * recipe's own ingredient coverage — so a recipe using all 3 supplied
 * ingredients scores 1.0 regardless of how many other ingredients it
 * also needs. recipe_ingredient_count is shown for context only.
 */
export interface ReverseMatchedRecipe {
  id: string
  name: string
  cuisine: string | null
  meal_type: string | null
  cook_time_minutes: number | null
  match_percentage: number
  matched_ingredient_names: string[]
  recipe_ingredient_count: number
}

export interface ReverseSearchResults {
  results: ReverseMatchedRecipe[]
  total_matched: number
}
