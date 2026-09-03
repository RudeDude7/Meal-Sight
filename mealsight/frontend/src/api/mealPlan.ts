import { apiRequest } from '@/api/client'
import type { MealPlanRequest, MealPlanResult } from '@/types/mealPlan'

/** POST /api/meal-plan — a real agent-layer orchestration call, not a fast proxy; see LoadingView usage on the Meal Plan page. */
export async function createMealPlan(
  request: MealPlanRequest,
  signal?: AbortSignal,
): Promise<MealPlanResult> {
  return apiRequest<MealPlanResult>('/api/meal-plan', { method: 'POST', body: request, signal })
}
