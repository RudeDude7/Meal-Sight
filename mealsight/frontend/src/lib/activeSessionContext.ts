import { createContext, useContext } from 'react'

export interface ActiveSessionContextValue {
  /** The current recommendation's own real session id, or null when idle. */
  traceId: string | null
  setTraceId: (traceId: string | null) => void
}

export const ActiveSessionContext = createContext<ActiveSessionContextValue | null>(null)

export function useActiveSession(): ActiveSessionContextValue {
  const context = useContext(ActiveSessionContext)
  if (!context) {
    throw new Error('useActiveSession must be used within an ActiveSessionProvider')
  }
  return context
}
