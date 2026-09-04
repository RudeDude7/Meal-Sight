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
 * cuisine_preference_data_points is the real ratings-count behind each
 * of those scores (mealsight/user_intelligence/scoring.py's own
 * preference_scores.data_points) — never inflated by that module's own
 * smoothing prior, so a score near 0.5 from one rating and a score near
 * 0.5 from ten stay distinguishable by data_points even though their
 * scores alone would look nearly identical.
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
  cuisine_preference_data_points: Record<string, number>
}

export type TasteInsightsTimeRange = 'this_week' | 'this_month' | 'all_time'

/**
 * What GET /api/insights returns. When sufficient_history is false,
 * every statistic is null and message explains why — mealsight.user_
 * intelligence.taste_insights never computes real-looking numbers over
 * a handful of meals.
 */
export interface TasteInsights {
  time_range: TasteInsightsTimeRange
  sufficient_history: boolean
  message: string | null
  total_meals_cooked: number
  most_cooked_cuisine: string | null
  average_rating: number | null
  protein_variety_score: number | null
  cooking_frequency_per_week: number | null
  preferred_cook_time_minutes: number | null
  stated_preferred_cook_time_minutes: number
  suggestions: string[]
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
  // Optional sixth (weather) signal — null together whenever no weather
  // data is available (see backend mealsight.utils.weather). Not
  // currently rendered directly anywhere; the model's own free-text
  // context_reasoning (ReasoningPanel.tsx) is what actually surfaces
  // weather to the user, the same way it already surfaces every other
  // context signal.
  temperature_f: number | null
  conditions: string | null
  mood_suggestion: string | null
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
