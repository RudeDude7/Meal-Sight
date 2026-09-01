interface CuisinePreferenceBarsProps {
  scores: Record<string, number>
  dataPoints: Record<string, number>
}

// mealsight/user_intelligence/scoring.py's own PREFERENCE_SMOOTHING_
// PRIOR_WEIGHT (3.0): a score built from fewer than 3 real ratings is
// still mostly the neutral prior, not real signal — rendered at lower
// opacity so a glance distinguishes "one rating" from "five ratings"
// even when their shrunk scores land close together (the task's own
// literal example: 0.625 from one rating vs. 0.781 from five).
const LOW_CONFIDENCE_THRESHOLD = 3

/**
 * Read-only — cuisine_preferences is computed from meal ratings, never
 * user-set. Each bar's own data_points count is shown alongside it,
 * never hidden, since the backend shrinks a low-data-point score toward
 * 0.5 (see scoring.py's own _shrink_toward_neutral) and a bar with no
 * count next to it would look like a confident 0.625 rather than what
 * it actually is: one rating's worth of evidence.
 */
export function CuisinePreferenceBars({ scores, dataPoints }: CuisinePreferenceBarsProps) {
  const cuisines = Object.keys(scores).sort((a, b) => (scores[b] ?? 0) - (scores[a] ?? 0))

  return (
    <div className="flex flex-col gap-3">
      {cuisines.map((cuisine) => {
        const score = scores[cuisine] ?? 0
        const points = dataPoints[cuisine] ?? 0
        const lowConfidence = points < LOW_CONFIDENCE_THRESHOLD
        return (
          <div key={cuisine}>
            <div className="flex items-baseline justify-between">
              <span className="text-body-lg capitalize text-ink-900">{cuisine}</span>
              <span className="font-mono text-label text-steel-400">
                {score.toFixed(3)} · {points} rating{points === 1 ? '' : 's'}
                {lowConfidence ? ' (low confidence)' : ''}
              </span>
            </div>
            <div className="mt-1 h-3 w-full rounded-sm bg-paper-1">
              <div
                className={[
                  'h-3 rounded-sm bg-signal-active',
                  lowConfidence ? 'opacity-40' : 'opacity-100',
                ].join(' ')}
                style={{ width: `${Math.round(score * 100)}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
