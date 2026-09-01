import { useEffect, useState } from 'react'

import { getRecipe } from '@/api/recipes'
import { deriveIconCategory } from '@/lib/proteinIcon'
import type { IconCategory } from '@/lib/proteinIcon'

// Module-level cache, shared across every call site — a History page
// can render many Tickets referencing the same handful of recipe_ids
// (a favorite gets cooked, or recommended, more than once), and there's
// no reason to re-fetch the same recipe's own ingredient list twice
// just to derive the same icon category twice.
const cache = new Map<string, IconCategory>()

/**
 * RecipeIcon's own category is derived from a recipe's real ingredient
 * names (src/lib/proteinIcon.ts), which History's own list endpoints
 * (get_meal_history, get_interaction_history) never return — only
 * recipe_id/recipe_name. This fetches the one real, already-existing
 * GET /api/recipes/{id} (the same endpoint the recommendation result
 * view already uses for the identical reason) to get the real
 * ingredient list, rather than guessing a category from the recipe's
 * name string alone.
 */
export function useRecipeIconCategory(recipeId: string | null): IconCategory | null {
  const [category, setCategory] = useState<IconCategory | null>(
    recipeId ? (cache.get(recipeId) ?? null) : null,
  )

  useEffect(() => {
    if (!recipeId) {
      setCategory(null)
      return
    }
    const cached = cache.get(recipeId)
    if (cached) {
      setCategory(cached)
      return
    }
    let cancelled = false
    getRecipe(recipeId)
      .then((detail) => {
        const derived = deriveIconCategory(detail.ingredients.map((ing) => ing.name))
        cache.set(recipeId, derived)
        if (!cancelled) setCategory(derived)
      })
      .catch(() => {
        // No icon rather than a guessed one — consistent with this
        // system's own "don't fake it" rule elsewhere.
      })
    return () => {
      cancelled = true
    }
  }, [recipeId])

  return category
}
