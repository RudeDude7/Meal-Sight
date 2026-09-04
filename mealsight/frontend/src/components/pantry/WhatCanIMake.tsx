import { useState } from 'react'

import { ApiError } from '@/api/client'
import { getRecipeByIngredients } from '@/api/recipes'
import { Button } from '@/components/primitives/Button'
import { EmptyState } from '@/components/primitives/EmptyState'
import { Ticket } from '@/components/primitives/Ticket'
import type { ReverseMatchedRecipe } from '@/types/recipe'

interface WhatCanIMakeProps {
  pantryItemNames: string[]
}

/**
 * Reverse search, placed on the Pantry page rather than a separate
 * search page — "what can I make with what I have" is closer to this
 * product's own core question than a generic ingredient-search page
 * would be, and it reuses the pantry's own real item names as input
 * rather than asking for them again. GET /api/recipes/by-ingredients
 * (mealsight.recipe_engine.reverse_search) ranks by what PROPORTION of
 * the pantry a recipe actually uses, not how much of its own ingredient
 * list happens to be covered — see that module's own docstring.
 */
export function WhatCanIMake({ pantryItemNames }: WhatCanIMakeProps) {
  const [results, setResults] = useState<ReverseMatchedRecipe[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSearch(): Promise<void> {
    setLoading(true)
    setError(null)
    try {
      const response = await getRecipeByIngredients(pantryItemNames)
      setResults(response.results)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not search recipes.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-heading text-ink-900">What can I make?</h3>
        <Button
          variant="secondary"
          onClick={() => void handleSearch()}
          disabled={loading || pantryItemNames.length === 0}
        >
          {loading ? 'Searching…' : 'Find recipes'}
        </Button>
      </div>

      {error && <p className="mt-2 text-body-lg text-signal-negative">{error}</p>}

      {results !== null && (
        <div className="mt-3">
          {results.length === 0 ? (
            <EmptyState
              illustration="spike"
              message="No recipes use a high enough proportion of what's in your pantry yet."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {results.map((recipe) => (
                <Ticket key={recipe.id} padding="compact">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-body-lg text-ink-900">{recipe.name}</p>
                      <p className="text-label text-steel-400">
                        {recipe.cuisine ?? 'cuisine unknown'} · uses{' '}
                        {recipe.matched_ingredient_names.join(', ')}
                      </p>
                    </div>
                    <span className="font-mono text-label text-signal-active">
                      {Math.round(recipe.match_percentage * 100)}%
                    </span>
                  </div>
                </Ticket>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
