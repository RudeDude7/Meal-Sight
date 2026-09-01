import { useState } from 'react'

import { rateMeal } from '@/api/history'
import { ApiError } from '@/api/client'
import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { useRecipeIconCategory } from '@/lib/useRecipeIconCategory'
import type { RateMealResponse } from '@/types/cook'
import type { MealHistoryEntry } from '@/types/profile'

interface MealHistoryTicketProps {
  meal: MealHistoryEntry
}

/**
 * An unrated meal gets an inline 1-5 rating control right on its own
 * Ticket — POSTs to /api/history/{meal_id}/rate. A successful rating
 * is the SUCCESS pattern: the response's own real updated cuisine_
 * preferences/protein_preference, shown right there, since that's the
 * actual visible payoff of the learning loop this whole profile is
 * built around — not a generic "saved" toast.
 */
export function MealHistoryTicket({ meal }: MealHistoryTicketProps) {
  const [currentRating, setCurrentRating] = useState(meal.rating)
  const [ratingResult, setRatingResult] = useState<RateMealResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const iconCategory = useRecipeIconCategory(meal.recipe_id)

  async function handleRate(value: number): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const result = await rateMeal(meal.id, value)
      setCurrentRating(value)
      setRatingResult(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that rating.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Ticket padding="compact">
      <div className="flex items-start gap-4">
        {iconCategory && <RecipeIcon category={iconCategory} />}
        <div className="flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-body-lg text-ink-900">{meal.recipe_name}</span>
            <span className="text-label text-steel-400">{meal.date}</span>
          </div>
          <p className="text-label text-steel-400">
            {[
              meal.cuisine,
              meal.meal_type,
              meal.servings_made ? `${meal.servings_made} serving(s)` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>

          {currentRating !== null ? (
            <p className="mt-2 text-body-lg text-ink-900">Rated {currentRating}/5</p>
          ) : (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-label text-ink-600">Rate this meal:</span>
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => void handleRate(value)}
                  disabled={submitting}
                  className="h-8 w-8 rounded-sm border border-ink-900/10 text-body-lg text-ink-600 hover:border-signal-active hover:text-signal-active"
                >
                  {value}
                </button>
              ))}
            </div>
          )}

          {error && <p className="mt-2 text-label text-signal-negative">{error}</p>}

          {ratingResult && (
            <div className="mt-3 flex items-center gap-2 rounded-sm border border-signal-positive/20 bg-signal-positive/10 px-3 py-2">
              <Stamp signal="positive">rated</Stamp>
              <span className="text-label text-ink-900">
                {meal.cuisine && ratingResult.cuisine_preferences
                  ? `${meal.cuisine} preference updated: ${ratingResult.cuisine_preferences[meal.cuisine]?.toFixed(3)}`
                  : 'Preferences updated.'}
              </span>
            </div>
          )}
        </div>
      </div>
    </Ticket>
  )
}
