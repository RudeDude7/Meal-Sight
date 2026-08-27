import type { HealthReport } from '@/types/health'

// Not built on apiRequest: GET /health returns a REAL HealthReport body
// even on its 503 ("degraded") response — the status code alone
// signals trouble, but the body is never the {code,message,trace_id}
// error envelope every other endpoint uses. Treating 503 here as a
// generic ApiError would throw away the one thing this call exists to
// return: which check actually failed.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** GET /health — note: no /api prefix, matches the backend's own route. */
export async function getHealth(signal?: AbortSignal): Promise<HealthReport> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal })
  return (await response.json()) as HealthReport
}
