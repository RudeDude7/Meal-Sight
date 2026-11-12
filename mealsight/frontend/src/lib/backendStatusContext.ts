import { createContext, useContext } from 'react'

import type { HealthReport } from '@/types/health'

/**
 * 'waking': the backend did not answer /health with a health report. On a free host that sleeps when idle
 * this is the normal state for the first minute after a long gap, not an error. The default (no provider,
 * e.g. in tests) is 'ready' so nothing is blocked.
 */
export type BackendPhase = 'checking' | 'ready' | 'waking'

export interface BackendStatus {
  phase: BackendPhase
  health: HealthReport | null
  /** Seconds since the backend first failed to answer; 0 when it is answering. */
  secondsWaiting: number
}

export const BackendStatusContext = createContext<BackendStatus>({
  phase: 'ready',
  health: null,
  secondsWaiting: 0,
})

export function useBackendStatus(): BackendStatus {
  return useContext(BackendStatusContext)
}
