import { Button } from '@/components/primitives/Button'
import { Stamp } from '@/components/primitives/Stamp'

interface PageErrorProps {
  message: string
  onRetry: () => void
}

/**
 * NEGATIVE state pattern for a failed page load: signal-negative Stamp,
 * a plain-language explanation, and always a concrete next action — the
 * retry button itself, never a dead end.
 */
export function PageError({ message, onRetry }: PageErrorProps) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-sm border border-signal-negative/20 bg-signal-negative/10 p-4">
      <Stamp signal="negative">couldn't load</Stamp>
      <p className="text-body-lg text-ink-900">{message}</p>
      <Button variant="secondary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
