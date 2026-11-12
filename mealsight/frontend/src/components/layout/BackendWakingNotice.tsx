import { Strip } from '@/components/primitives/Strip'
import { Well } from '@/components/primitives/Well'
import { useBackendStatus } from '@/lib/backendStatusContext'

/**
 * Shown only while the backend is not answering. The free host sleeps when idle, so the first visit after a
 * gap waits for it to start; that is expected, not a failure, and it retries by itself. Reuses the Strip
 * (a ticking elapsed-seconds stamp plus a plain message), the same pattern the pipeline view uses for a
 * step that is still running.
 */
export function BackendWakingNotice() {
  const { phase, secondsWaiting } = useBackendStatus()
  if (phase !== 'waking') return null
  return (
    <Well className="mb-6 px-3 py-1">
      <div role="status">
        <Strip
          timestamp={`${secondsWaiting}s`}
          message="The demo backend is waking up from sleep (free hosting). This can take a minute or more. This page will be ready on its own."
        />
      </div>
    </Well>
  )
}
