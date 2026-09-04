import { useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { getTasteInsights } from '@/api/insights'
import { EmptyState } from '@/components/primitives/EmptyState'
import { Ticket } from '@/components/primitives/Ticket'
import type { TasteInsights, TasteInsightsTimeRange } from '@/types/profile'

const TIME_RANGES: { value: TasteInsightsTimeRange; label: string }[] = [
  { value: 'this_week', label: 'This week' },
  { value: 'this_month', label: 'This month' },
  { value: 'all_time', label: 'All time' },
]

/**
 * Below the (read-only, rating-derived) cuisine preference bars —
 * same data lineage (meal_history), just behavioral analytics over it
 * rather than a per-cuisine score. Insufficient history uses the
 * EmptyState pattern, per this task's own explicit instruction, rather
 * than rendering a panel full of null-shaped stats.
 */
export function TasteInsightsPanel() {
  const [timeRange, setTimeRange] = useState<TasteInsightsTimeRange>('this_month')
  const [insights, setInsights] = useState<TasteInsights | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getTasteInsights(timeRange)
      .then((result) => {
        if (!cancelled) setInsights(result)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Could not load taste insights.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [timeRange])

  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-heading text-ink-900">Taste insights</h3>
        <div className="flex gap-1">
          {TIME_RANGES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setTimeRange(value)}
              className={[
                'rounded-sm px-2 py-1 text-label',
                timeRange === value
                  ? 'bg-ink-900 text-paper-0'
                  : 'text-ink-600 hover:bg-paper-1',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3">
        {loading && <p className="text-body-lg text-steel-400">Loading…</p>}

        {!loading && error && <p className="text-body-lg text-signal-negative">{error}</p>}

        {!loading && !error && insights && !insights.sufficient_history && (
          <EmptyState
            illustration="spike"
            message={insights.message ?? 'Not enough cooking history yet for insights.'}
          />
        )}

        {!loading && !error && insights && insights.sufficient_history && (
          <Ticket>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-label text-steel-400">Meals cooked</dt>
                <dd className="text-body-lg text-ink-900">{insights.total_meals_cooked}</dd>
              </div>
              <div>
                <dt className="text-label text-steel-400">Most-cooked cuisine</dt>
                <dd className="text-body-lg capitalize text-ink-900">
                  {insights.most_cooked_cuisine ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-label text-steel-400">Average rating</dt>
                <dd className="text-body-lg text-ink-900">
                  {insights.average_rating !== null ? insights.average_rating.toFixed(1) : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-label text-steel-400">Protein variety</dt>
                <dd className="text-body-lg text-ink-900">
                  {insights.protein_variety_score !== null
                    ? insights.protein_variety_score.toFixed(2)
                    : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-label text-steel-400">Cooking frequency</dt>
                <dd className="text-body-lg text-ink-900">
                  {insights.cooking_frequency_per_week !== null
                    ? `${insights.cooking_frequency_per_week.toFixed(1)}/week`
                    : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-label text-steel-400">Actual vs. stated cook time</dt>
                <dd className="text-body-lg text-ink-900">
                  {insights.preferred_cook_time_minutes !== null
                    ? `${insights.preferred_cook_time_minutes.toFixed(0)} vs ${insights.stated_preferred_cook_time_minutes} min`
                    : '—'}
                </dd>
              </div>
            </dl>

            {insights.suggestions.length > 0 && (
              <ul className="mt-4 flex flex-col gap-2 border-t border-ink-900/10 pt-4">
                {insights.suggestions.map((suggestion) => (
                  <li key={suggestion} className="text-body-lg text-ink-900">
                    {suggestion}
                  </li>
                ))}
              </ul>
            )}
          </Ticket>
        )}
      </div>
    </div>
  )
}
