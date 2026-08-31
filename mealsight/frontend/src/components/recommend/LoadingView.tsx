import { useEffect, useState } from 'react'

import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Strip } from '@/components/primitives/Strip'

export interface LoadingStrip {
  id: string | number
  timestamp: string
  message: string
}

interface LoadingViewProps {
  /** Date.now() at the moment this run actually started. */
  startedAt: number
  /** Already-batched (see useBatchedList) — see that hook's own docstring for why. */
  strips: LoadingStrip[]
}

function useElapsedSeconds(startedAt: number): number {
  const [elapsed, setElapsed] = useState(() => (Date.now() - startedAt) / 1000)

  useEffect(() => {
    // 100ms tick — fine enough that a tenths-place display visibly
    // moves every frame it updates, coarse enough that it costs
    // nothing measurable over an 11-second run.
    const interval = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 100)
    return () => clearInterval(interval)
  }, [startedAt])

  return elapsed
}

/**
 * The loading view as the showpiece it deserves to be, not a spinner —
 * a real run takes ~11.3 seconds and the user watches all of it. Three
 * pieces, each honest about what it's showing: the animated RecipeIcon
 * (category="loading" — a neutral cooking-pot icon, since which recipe
 * this run will land on is genuinely still unknown while the agent
 * works, so nothing protein-specific would be true yet), a live
 * elapsed timer in tenths (so it visibly moves continuously, not just
 * once a message happens to arrive — this is what tells someone the
 * system is still alive during perceive's own real ~11s of silence
 * between heartbeats), and a column of Strips printing in as messages
 * actually arrive. This is also the one place in the whole app the
 * motion rule genuinely permits animation (icon idle-bob, timer
 * ticking, each Strip's own print-in) — because something is, for the
 * whole time this view is on screen, genuinely, currently happening.
 */
export function LoadingView({ startedAt, strips }: LoadingViewProps) {
  const elapsedSeconds = useElapsedSeconds(startedAt)

  return (
    <div className="flex flex-col items-center gap-6 rounded-sm border border-ink-900 bg-paper-raised p-8">
      <RecipeIcon category="loading" animated size="large" />
      <div className="font-mono text-title tabular-nums text-signal-active" aria-live="polite">
        {elapsedSeconds.toFixed(1)}s
      </div>
      <div className="w-full">
        {strips.map((strip) => (
          <Strip key={strip.id} timestamp={strip.timestamp} message={strip.message} />
        ))}
      </div>
    </div>
  )
}
