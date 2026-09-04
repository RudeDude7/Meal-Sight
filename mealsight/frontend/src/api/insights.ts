import { apiRequest } from '@/api/client'
import type { TasteInsights, TasteInsightsTimeRange } from '@/types/profile'

/** GET /api/insights */
export async function getTasteInsights(
  timeRange: TasteInsightsTimeRange = 'this_month',
  signal?: AbortSignal,
): Promise<TasteInsights> {
  return apiRequest<TasteInsights>('/api/insights', { query: { time_range: timeRange }, signal })
}
