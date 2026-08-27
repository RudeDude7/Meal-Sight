import type { ApiErrorEnvelope } from '@/types/errors'

// Empty string in production means "same origin as the deployed
// frontend" (a real API_BASE_URL should be set for that case); empty
// in local dev means "relative path", which vite.config.ts's own dev
// proxy forwards to the real backend — no CORS involved either way.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** Thrown for any non-2xx response — carries the backend's own error envelope. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly traceId: string | null

  constructor(status: number, envelope: ApiErrorEnvelope) {
    super(envelope.message)
    this.name = 'ApiError'
    this.status = status
    this.code = envelope.code
    this.traceId = envelope.trace_id
  }
}

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

async function parseErrorEnvelope(response: Response): Promise<ApiErrorEnvelope> {
  try {
    const body: unknown = await response.json()
    if (
      body !== null &&
      typeof body === 'object' &&
      'code' in body &&
      'message' in body &&
      typeof (body as Record<string, unknown>).code === 'string' &&
      typeof (body as Record<string, unknown>).message === 'string'
    ) {
      const record = body as Record<string, unknown>
      return {
        code: record.code as string,
        message: record.message as string,
        trace_id: typeof record.trace_id === 'string' ? record.trace_id : null,
      }
    }
  } catch {
    // response body wasn't JSON at all (e.g. a proxy/network-level failure) — fall through
  }
  return {
    code: 'unknown_error',
    message: `Request failed with status ${response.status}.`,
    trace_id: null,
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorEnvelope(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

type QueryValue = string | number | boolean | undefined | null | string[]

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryValue>
  body?: unknown
  signal?: AbortSignal
}

// FastAPI's own query-param parsing expects a REPEATED key for a
// list[str] parameter (?dietary_filters=a&dietary_filters=b), not one
// comma-joined value — this appends once per array element to match.
function buildQueryString(query: RequestOptions['query']): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, item)
    } else {
      params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

/** JSON request/response helper used by every typed endpoint function below. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal } = options
  const response = await fetch(`${buildUrl(path)}${buildQueryString(query)}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
  return handleResponse<T>(response)
}

/** multipart/form-data request helper — POST /api/recommend is the one caller. */
export async function apiRequestMultipart<T>(
  path: string,
  formData: FormData,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(buildUrl(path), { method: 'POST', body: formData, signal })
  return handleResponse<T>(response)
}

/** Resolves the same-origin-relative WebSocket URL for a session (proxied in dev). */
export function websocketUrl(path: string): string {
  const base = API_BASE_URL || window.location.origin
  const url = new URL(path, base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}
