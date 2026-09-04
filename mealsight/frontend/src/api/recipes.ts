import { apiRequest } from '@/api/client'
import type { RecipeDetail, ReverseSearchResults, SearchResults } from '@/types/recipe'

export interface SearchRecipesParams {
  dietary_filters?: string[]
  max_cook_time?: number
  cuisine?: string
  meal_type?: string
  max_results?: number
}

/** GET /api/recipes/search */
export async function searchRecipes(
  params: SearchRecipesParams = {},
  signal?: AbortSignal,
): Promise<SearchResults> {
  return apiRequest<SearchResults>('/api/recipes/search', { query: { ...params }, signal })
}

/** GET /api/recipes/{id} */
export async function getRecipe(recipeId: string, signal?: AbortSignal): Promise<RecipeDetail> {
  return apiRequest<RecipeDetail>(`/api/recipes/${encodeURIComponent(recipeId)}`, { signal })
}

/** GET /api/recipes/by-ingredients — "what can I make with what I have." */
export async function getRecipeByIngredients(
  ingredients: string[],
  minimumMatchPercentage = 0.6,
  signal?: AbortSignal,
): Promise<ReverseSearchResults> {
  return apiRequest<ReverseSearchResults>('/api/recipes/by-ingredients', {
    query: { ingredients, minimum_match_percentage: minimumMatchPercentage },
    signal,
  })
}
