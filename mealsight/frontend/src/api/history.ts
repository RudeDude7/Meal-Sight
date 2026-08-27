import { apiRequest } from '@/api/client'
import type { RateMealResponse } from '@/types/cook'
import type { MealHistoryEntry } from '@/types/profile'

export interface GetHistoryParams {
  days_back?: number
  cuisine_filter?: string
  rating_filter?: number
}

export interface MealHistoryResponse {
  meals: MealHistoryEntry[]
  count: number
}

/** GET /api/history */
export async function getHistory(
  params: GetHistoryParams = {},
  signal?: AbortSignal,
): Promise<MealHistoryResponse> {
  return apiRequest<MealHistoryResponse>('/api/history', { query: { ...params }, signal })
}

/** POST /api/history/{meal_id}/rate */
export async function rateMeal(
  mealId: number,
  rating: number,
  signal?: AbortSignal,
): Promise<RateMealResponse> {
  return apiRequest<RateMealResponse>(`/api/history/${mealId}/rate`, {
    method: 'POST',
    body: { rating },
    signal,
  })
}
