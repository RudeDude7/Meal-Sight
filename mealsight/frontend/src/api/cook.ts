import { apiRequest } from '@/api/client'
import type { CookRequest, CookResponse } from '@/types/cook'

/** POST /api/cook — the only endpoint that mutates meal history and deducts from the pantry. */
export async function postCook(body: CookRequest, signal?: AbortSignal): Promise<CookResponse> {
  return apiRequest<CookResponse>('/api/cook', { method: 'POST', body, signal })
}
