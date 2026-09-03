// Mirrors mealsight.agent.meal_planner's own plain-dict result shape
// (there is no dedicated pydantic model for it — see that module's own
// docstring on why the composite result stays a plain dict) and
// mealsight.planning.models.DayAssignment.

import type { GroceryList } from '@/types/pantry'

export interface MealPlanRequest {
  days: number
  servings: number
  dietary_restrictions?: string[]
  max_cook_time_minutes?: number
  avoid_ingredients?: string[]
}

export interface MealPlanDay {
  day_index: number
  recipe_id: string
  recipe_name: string
  cuisine: string | null
  protein_type: string | null
  servings: number
  match_score: number
  can_cook: boolean
  uses_expiring_ingredient_names: string[]
  missing_ingredient_names: string[]
  /** Missing ingredients this day shares with at least one EARLIER day — the direct proof the overlap optimization did something. */
  shared_missing_ingredient_names: string[]
  cuisine_repeat_forced: boolean
}

export interface MealPlanNutritionSummary {
  total_calories: number
  total_protein_g: number
  total_carbs_g: number
  total_fat_g: number
  total_fiber_g: number
  total_sodium_mg: number
  days_with_nutrition: number
  days_total: number
  coverage_note: string
}

export interface MealPlanResult {
  days: MealPlanDay[]
  grocery_list: GroceryList | null
  total_distinct_ingredients: number
  shared_ingredient_count: number
  nutrition_summary: MealPlanNutritionSummary
  wall_clock_seconds: number
  trace_id: string
}
