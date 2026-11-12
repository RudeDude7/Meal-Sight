import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { getHealth } from '@/api/health'
import { BackendStatusContext } from '@/lib/backendStatusContext'
import type { BackendPhase } from '@/lib/backendStatusContext'
import type { HealthReport } from '@/types/health'

const WAKING_POLL_MS = 4000
const READY_POLL_MS = 15000
const PROBE_TIMEOUT_MS = 8000
// One failed probe after a healthy one is a blip; two in a row means the backend really went away.
const FAILURES_BEFORE_WAKING = 2

function isHealthReport(body: unknown): body is HealthReport {
  return body !== null && typeof body === 'object' && 'mcp_servers' in body
}

/**
 * Polls GET /health. While the backend is not answering (a sleeping free-tier host returns an HTML wake
 * page, a timeout or a network error, never a health report) the phase is 'waking' and the UI says so,
 * retrying every few seconds, instead of showing an error. Once healthy it keeps polling slowly while the
 * tab is visible so the demo notice can show how many recommendations are already in progress. A 503 that
 * still carries a health report counts as reachable: the backend is up, a provider is just degraded.
 */
export function BackendStatusProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<BackendPhase>('checking')
  const [health, setHealth] = useState<HealthReport | null>(null)
  const [firstFailureAt, setFirstFailureAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const failures = useRef(0)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function probe(): Promise<void> {
      const controller = new AbortController()
      const abortTimer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
      let reachable = false
      try {
        const body: unknown = await getHealth(controller.signal)
        if (isHealthReport(body)) {
          reachable = true
          if (!cancelled) {
            setHealth(body)
            setPhase('ready')
            setFirstFailureAt(null)
          }
        }
      } catch {
        // network error, abort, or a non-JSON wake page: treated as "not answering yet"
      } finally {
        clearTimeout(abortTimer)
      }
      if (cancelled) return
      if (reachable) {
        failures.current = 0
      } else {
        failures.current += 1
        if (failures.current >= FAILURES_BEFORE_WAKING || phaseIsNotReadyYet()) {
          setPhase('waking')
          setFirstFailureAt((previous) => previous ?? Date.now())
        }
      }
      const delay = reachable ? READY_POLL_MS : WAKING_POLL_MS
      timer = setTimeout(() => {
        if (reachable && document.visibilityState === 'hidden') {
          // do not poll a backgrounded tab; check again when it comes back
          const onVisible = (): void => {
            document.removeEventListener('visibilitychange', onVisible)
            void probe()
          }
          document.addEventListener('visibilitychange', onVisible)
          return
        }
        void probe()
      }, delay)
    }

    // 'checking' (first probe) counts as not-ready: one failure already means the backend is not up.
    function phaseIsNotReadyYet(): boolean {
      return phaseRef.current !== 'ready'
    }

    void probe()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  const phaseRef = useRef<BackendPhase>('checking')
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  useEffect(() => {
    if (phase !== 'waking') return
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [phase])

  const secondsWaiting =
    phase === 'waking' && firstFailureAt !== null
      ? Math.max(0, Math.round((now - firstFailureAt) / 1000))
      : 0

  return (
    <BackendStatusContext.Provider value={{ phase, health, secondsWaiting }}>
      {children}
    </BackendStatusContext.Provider>
  )
}
