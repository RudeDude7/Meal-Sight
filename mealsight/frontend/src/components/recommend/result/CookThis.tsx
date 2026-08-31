import { useState } from 'react'

import { postCook } from '@/api/cook'
import { ApiError } from '@/api/client'
import { Button } from '@/components/primitives/Button'
import { Stamp } from '@/components/primitives/Stamp'
import { Well } from '@/components/primitives/Well'
import type { CookResponse } from '@/types/cook'

interface CookThisProps {
  recipeId: string
  defaultServings: number
  /** Used only to describe a preference-score change in plain language, if one happened. */
  cuisine: string | null
}

type Status = 'form' | 'submitting' | 'success' | 'error'

function preferenceChangeText(
  cuisine: string | null,
  before: CookResponse['preferences_before'],
  after: CookResponse['preferences_after'],
): string | null {
  if (!cuisine || !before || !after) return null
  const beforeScore = before.cuisine_preferences[cuisine] ?? 0
  const afterScore = after.cuisine_preferences[cuisine] ?? 0
  if (afterScore === beforeScore) return null
  const direction = afterScore > beforeScore ? 'up' : 'down'
  return `${cuisine} preference moved ${direction}: ${beforeScore.toFixed(2)} → ${afterScore.toFixed(2)}`
}

/**
 * Confirms servings, optionally captures a 1-5 rating, POSTs to
 * /api/cook. On success this is the SUCCESS state pattern: a signal-
 * positive Stamp, upright, plus what was actually logged and changed —
 * never just a generic "done" toast. An idempotent replay (the same
 * idempotency_key computed twice — see cook.py's own module docstring)
 * is rendered as this exact same success view, not an error: the meal
 * really was logged, whether this is the first time this endpoint
 * computed that or the second time it replayed the first answer.
 */
export function CookThis({ recipeId, defaultServings, cuisine }: CookThisProps) {
  const [servings, setServings] = useState(defaultServings)
  const [rating, setRating] = useState<number | null>(null)
  const [status, setStatus] = useState<Status>('form')
  const [response, setResponse] = useState<CookResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleCook(): Promise<void> {
    setStatus('submitting')
    setError(null)
    try {
      const result = await postCook({
        recipe_id: recipeId,
        servings_made: servings,
        rating,
      })
      setResponse(result)
      setStatus('success')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not log this as cooked.')
      setStatus('error')
    }
  }

  if (status === 'success' && response) {
    const changeText = preferenceChangeText(
      cuisine,
      response.preferences_before,
      response.preferences_after,
    )
    return (
      <Well className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <Stamp signal="positive">cooked</Stamp>
          {response.idempotent_replay && (
            <span className="text-label text-steel-400">(already logged earlier)</span>
          )}
        </div>
        <p className="text-body-lg text-ink-900">
          Logged {response.meal.recipe_name} — {response.meal.servings_made} serving(s) on{' '}
          {response.meal.date}
          {response.meal.rating !== null ? `, rated ${response.meal.rating}/5` : ''}.
        </p>

        {response.deducted.length > 0 && (
          <div>
            <p className="text-label font-medium text-ink-600">Pantry updated</p>
            <ul className="mt-1 flex flex-col gap-1">
              {response.deducted.map((item) => (
                <li key={item.name} className="text-body-lg text-ink-900">
                  {item.name}: {item.before} → {item.after}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Partial-failure disclosure — the meal WAS genuinely logged
            (log_meal runs before remove_items, see cook.py's own
            docstring), so this stays inside the Success view as an
            honest caveat, not recast as an error. */}
        {response.pantry_deduction_error && (
          <p className="text-label text-signal-info">
            Pantry wasn't fully updated: {response.pantry_deduction_error}
          </p>
        )}

        {changeText && <p className="text-label text-ink-600">{changeText}</p>}
      </Well>
    )
  }

  return (
    <Well className="flex flex-col gap-4 p-4">
      <h3 className="text-heading text-ink-900">Cook this?</h3>

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Servings made</span>
          <input
            type="number"
            min={1}
            value={servings}
            onChange={(event) => setServings(Math.max(1, Number(event.target.value)))}
            disabled={status === 'submitting'}
            className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>

        <div className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Rating (optional)</span>
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRating(rating === value ? null : value)}
                disabled={status === 'submitting'}
                aria-pressed={rating === value}
                className={[
                  'h-8 w-8 rounded-sm border text-body-lg',
                  rating !== null && value <= rating
                    ? 'border-signal-active bg-signal-active/10 text-signal-active'
                    : 'border-ink-900/10 text-ink-600',
                ].join(' ')}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        <Button variant="primary" onClick={handleCook} disabled={status === 'submitting'}>
          {status === 'submitting' ? 'Logging…' : 'Cook This'}
        </Button>
      </div>

      {/* NEGATIVE pattern for a genuine request failure — never reached
          on an idempotent replay, only on a real thrown ApiError. */}
      {status === 'error' && error && <p className="text-label text-signal-negative">{error}</p>}
    </Well>
  )
}
