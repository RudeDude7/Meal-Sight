import { apiRequest } from '@/api/client'
import type { LogWasteInput, WasteLogResult, WasteStats, WasteTimeRange } from '@/types/pantry'

/** POST /api/waste — logs a waste event and deducts it from the pantry in the same call. */
export async function logWaste(
  item: LogWasteInput,
  signal?: AbortSignal,
): Promise<WasteLogResult> {
  return apiRequest<WasteLogResult>('/api/waste', { method: 'POST', body: item, signal })
}

/** GET /api/waste */
export async function getWasteStats(
  timeRange: WasteTimeRange = 'this_week',
  signal?: AbortSignal,
): Promise<WasteStats> {
  return apiRequest<WasteStats>('/api/waste', { query: { time_range: timeRange }, signal })
}
