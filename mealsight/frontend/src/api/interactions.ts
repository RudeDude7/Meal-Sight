import { apiRequest } from '@/api/client'
import type { InteractionRecord } from '@/types/profile'

export interface GetInteractionsParams {
  days_back?: number
  limit?: number
}

export interface InteractionHistoryResponse {
  interactions: InteractionRecord[]
  count: number
}

/** GET /api/interactions — every recommendation request and its outcome, cooked or not. */
export async function getInteractions(
  params: GetInteractionsParams = {},
  signal?: AbortSignal,
): Promise<InteractionHistoryResponse> {
  return apiRequest<InteractionHistoryResponse>('/api/interactions', {
    query: { ...params },
    signal,
  })
}
