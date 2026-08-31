import { useState } from 'react'
import type { ReactNode } from 'react'

import { ActiveSessionContext } from '@/lib/activeSessionContext'

/**
 * Holds the current recommendation session's own real id (mealsight/
 * api/routers/recommend.py's own session_id, which the backend also
 * uses as the agent run's trace_id — see mealsight.agent.runner) so
 * the masthead's ticket number can be REAL data, not decorative: "NO.
 * {trace_id}" while a run is actually in flight, a stable placeholder
 * otherwise. The system's own honesty principle — never fake a number
 * that looks like it means something — is exactly why this exists as
 * shared state instead of the masthead just always showing a fixed
 * string.
 *
 * The context object and the useActiveSession hook both live in
 * src/lib/activeSessionContext.ts, not here — react-refresh's own
 * fast-refresh only works reliably in a file that exports components
 * alone, and this file needs to export this one component.
 */
export function ActiveSessionProvider({ children }: { children: ReactNode }) {
  const [traceId, setTraceId] = useState<string | null>(null)
  return (
    <ActiveSessionContext.Provider value={{ traceId, setTraceId }}>
      {children}
    </ActiveSessionContext.Provider>
  )
}
