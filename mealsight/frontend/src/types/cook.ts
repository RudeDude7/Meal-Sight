// Mirrors mealsight/api/routers/cook.py (CookRequest) and history.py
// (RateMealRequest) — the cook-confirmation and rating flows.

import type { MealHistoryEntry } from '@/types/profile'
import type { UserProfile } from '@/types/profile'

export interface CookRequest {
  recipe_id: string
  servings_made: number
  ingredients_used?: string[] | null
  rating?: number | null
  idempotency_key?: string | null
}

export interface DeductedIngredient {
  name: string
  before: number
  after: number
  quantity_removed: number
}

export type SkipReason = 'not_in_recipe' | 'not_in_pantry' | 'quantity_unknown'

export interface SkippedIngredient {
  name: string
  reason: SkipReason
}

/** POST /api/cook's own response — see cook.py's own module docstring. */
export interface CookResponse {
  meal: MealHistoryEntry
  deducted: DeductedIngredient[]
  skipped: SkippedIngredient[]
  preferences_before: UserProfile | null
  preferences_after: UserProfile | null
  pantry_deduction_error: string | null
  idempotent_replay: boolean
}

export interface RateMealRequest {
  rating: number
}

/** POST /api/history/{meal_id}/rate's own response. */
export interface RateMealResponse {
  meal: MealHistoryEntry
  cuisine_preferences: Record<string, number> | undefined
  protein_preference: string | null | undefined
}
