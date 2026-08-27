// Mirrors mealsight/api/errors.py's own error_envelope() — the one
// error shape every failed API response returns, regardless of which
// endpoint or which exception produced it.

export interface ApiErrorEnvelope {
  code: string
  message: string
  trace_id: string | null
}
