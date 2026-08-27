import { apiRequest } from '@/api/client'
import type { GroceryList } from '@/types/pantry'

/** GET /api/grocery-list */
export async function getGroceryList(listId?: number, signal?: AbortSignal): Promise<GroceryList> {
  return apiRequest<GroceryList>('/api/grocery-list', { query: { list_id: listId }, signal })
}
