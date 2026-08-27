import { apiRequest } from '@/api/client'
import type {
  FreshnessFilter,
  PantryItem,
  PantryItemInput,
  PantryUpdateResult,
  RemovalResult,
} from '@/types/pantry'

export interface GetPantryParams {
  category?: string
  freshness_filter?: FreshnessFilter
  search?: string
}

export interface PantryResponse {
  items: PantryItem[]
  count: number
}

/** GET /api/pantry */
export async function getPantry(
  params: GetPantryParams = {},
  signal?: AbortSignal,
): Promise<PantryResponse> {
  return apiRequest<PantryResponse>('/api/pantry', { query: { ...params }, signal })
}

/** PATCH /api/pantry — add/update pantry items. */
export async function updatePantry(
  items: PantryItemInput[],
  signal?: AbortSignal,
): Promise<PantryUpdateResult> {
  return apiRequest<PantryUpdateResult>('/api/pantry', { method: 'PATCH', body: { items }, signal })
}

/** DELETE /api/pantry/{item_id} */
export async function deletePantryItem(
  itemId: number,
  signal?: AbortSignal,
): Promise<RemovalResult> {
  return apiRequest<RemovalResult>(`/api/pantry/${itemId}`, { method: 'DELETE', signal })
}
