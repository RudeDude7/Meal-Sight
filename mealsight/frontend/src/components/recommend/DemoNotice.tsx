import { Well } from '@/components/primitives/Well'
import { useBackendStatus } from '@/lib/backendStatusContext'

/**
 * Said BEFORE the visitor waits. The numbers come from GET /health (`demo`), which derives them from the
 * live rate-limit spec and the sessions currently running, so they stay true if the provider's limits
 * change. A photo recommendation makes three provider requests and a text-only one makes two; the first
 * is immediate and each further one waits for the next slot, so the floor is (requests - 1) x interval.
 * Plain notice, not a queue widget: everyone shares one limiter, so "N already running" is the whole story.
 */
export function DemoNotice() {
  const { health } = useBackendStatus()
  const demo = health?.demo
  const interval = demo?.seconds_between_requests ?? null
  const active = demo?.active_runs ?? 0

  return (
    <Well className="px-3 py-2">
      <p className="text-label text-ink-600">
        <strong className="font-medium text-ink-900">Free demo, so it is slow.</strong>{' '}
        {interval !== null ? (
          <>
            The AI provider lets one request start every {Math.round(interval)} seconds. A text-only
            request makes two, so allow at least {Math.round(interval)} seconds; with a photo it
            makes three, so allow at least {Math.round(interval * 2)} seconds.
          </>
        ) : (
          <>
            The AI provider&apos;s free tier allows only a few requests a minute, so a
            recommendation can take a minute or more.
          </>
        )}{' '}
        {active > 0
          ? `${active} recommendation${active === 1 ? ' is' : 's are'} already running; yours will wait behind ${active === 1 ? 'it' : 'them'}.`
          : 'Nothing else is running right now.'}{' '}
        The demo also resets whenever it restarts, so anything you save is temporary.
      </p>
    </Well>
  )
}
