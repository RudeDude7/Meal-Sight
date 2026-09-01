import { useEffect, useState } from 'react'

function useElapsedSeconds(startedAt: number): number {
  const [elapsed, setElapsed] = useState(() => (Date.now() - startedAt) / 1000)
  useEffect(() => {
    const interval = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 100)
    return () => clearInterval(interval)
  }, [startedAt])
  return elapsed
}

interface PageLoadingProps {
  label: string
}

/**
 * LOADING state pattern for a plain page fetch (Pantry, Grocery List):
 * signal-active, a live mono timer counting in tenths — the same visual
 * vocabulary the recommendation run's own LoadingView uses, scaled down
 * for a fetch that's typically much faster. No spinner, no motion
 * beyond the timer's own changing digits.
 */
export function PageLoading({ label }: PageLoadingProps) {
  const [startedAt] = useState(() => Date.now())
  const elapsed = useElapsedSeconds(startedAt)

  return (
    <div className="flex items-center gap-3 rounded-sm border border-ink-900/10 bg-paper-raised px-4 py-3">
      <span className="font-mono text-body-lg tabular-nums text-signal-active">
        {elapsed.toFixed(1)}s
      </span>
      <span className="text-body-lg text-ink-600">{label}</span>
    </div>
  )
}
