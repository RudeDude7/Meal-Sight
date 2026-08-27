// Mirrors mealsight/user_intelligence/models.py.

export type CookingSkill = 'beginner' | 'intermediate' | 'advanced'
export type BudgetSensitivity = 'budget' | 'moderate' | 'flexible'

export type PreferenceType =
  | 'dietary_restrictions'
  | 'disliked_ingredients'
  | 'preferred_cook_time_minutes'
  | 'household_size'
  | 'protein_preference'
  | 'cooking_skill'
  | 'budget_sensitivity'

/**
 * The full user profile, as returned by GET /api/profile.
 * cuisine_preferences is a {cuisine: score} map, 0.0-1.0, learned from
 * rated meals — empty until at least one meal has been rated.
 */
export interface UserProfile {
  dietary_restrictions: string[]
  disliked_ingredients: string[]
  preferred_cook_time_minutes: number
  household_size: number
  protein_preference: string | null
  cooking_skill: CookingSkill
  budget_sensitivity: BudgetSensitivity
  cuisine_preferences: Record<string, number>
}

/**
 * One meal_history row. rating is null for a meal logged but not yet
 * rated — POST /api/history/{id}/rate is the separate call that fills
 * it in later.
 */
export interface MealHistoryEntry {
  id: number
  recipe_id: string | null
  recipe_name: string
  cuisine: string | null
  meal_type: string | null
  date: string
  rating: number | null
  servings_made: number | null
  ingredients_used: string[] | null
  notes: string | null
  cooked_at: string
}

export type RepetitionRecommendation = 'acceptable' | 'suggest_alternative' | 'too_repetitive'

export interface RepetitionCheck {
  repetition_score: number
  reason: string
  recommendation: RepetitionRecommendation
  last_cooked: string | null
}

export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack'

export interface ContextSignals {
  meal_type: MealType
  complexity_suggestion: string
  context_notes: string[]
}

/**
 * One interaction_history row, as returned by GET /api/interactions —
 * every recommendation REQUEST and its outcome, regardless of whether
 * anything was ever cooked (MealHistoryEntry, above, only ever exists
 * for a confirmed cook). Text only: voice_transcript is the transcript
 * text itself, ingredients_summary a short description of what a photo
 * yielded — never the actual image or audio bytes.
 */
export interface InteractionRecord {
  id: number
  created_at: string
  trace_id: string | null
  modalities: string[]
  text_input: string | null
  voice_transcript: string | null
  ingredients_summary: string | null
  merged_constraints: Record<string, unknown> | null
  recommended_recipe_id: string | null
  recommended_recipe_name: string | null
  any_cookable: boolean
  top_match_score: number | null
  final_response: string | null
}
