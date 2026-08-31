import { useEffect, useState } from 'react'

import { getRecipe } from '@/api/recipes'
import { DietMarks } from '@/components/primitives/DietMarks'
import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { CookThis } from '@/components/recommend/result/CookThis'
import { MissingAndSubstitutions } from '@/components/recommend/result/MissingAndSubstitutions'
import { NutritionPanel } from '@/components/recommend/result/NutritionPanel'
import { ReasoningPanel } from '@/components/recommend/result/ReasoningPanel'
import { deriveDietaryMarks } from '@/lib/dietaryMarks'
import { deriveIconCategory } from '@/lib/proteinIcon'
import type { RecommendationResult } from '@/types/recommendation'
import type { RecipeDetail } from '@/types/recipe'

interface CookableResultProps {
  result: RecommendationResult
}

function matchQualifier(score: number): string {
  if (score >= 0.85) return 'excellent match'
  if (score >= 0.65) return 'good match'
  if (score >= 0.4) return 'partial match'
  return 'weak match'
}

/**
 * The one place recipe_id (flattened onto the top-level result
 * specifically so a client has one obvious field to read it from — see
 * mealsight/api/routers/recommend.py's own _serialize_result comment)
 * gets used for a SECOND real purpose beyond feeding /api/cook: scaled_
 * recipe carries name/cook_time/ingredients but has no cuisine, no
 * dietary_tags, and — critically — no steps at all (ScaledRecipe the
 * pydantic model genuinely has no steps field). Those only exist on
 * RecipeDetail, so this fetches it once, from the same already-existing
 * GET /api/recipes/{id} the Recipe browsing pages already use — not a
 * new endpoint, not a guess.
 */
export function CookableResult({ result }: CookableResultProps) {
  const [detail, setDetail] = useState<RecipeDetail | null>(null)
  const [detailError, setDetailError] = useState(false)

  const recipeId = result.recipe_id
  const scaled = result.scaled_recipe

  useEffect(() => {
    if (!recipeId) return
    let cancelled = false
    getRecipe(recipeId)
      .then((detail) => {
        if (!cancelled) setDetail(detail)
      })
      .catch(() => {
        if (!cancelled) setDetailError(true)
      })
    return () => {
      cancelled = true
    }
  }, [recipeId])

  if (!scaled || !recipeId) {
    return (
      <p className="text-body-lg text-ink-600">
        {result.final_response ?? 'A recipe was recommended, but the full details are unavailable.'}
      </p>
    )
  }

  const matchedNames = new Set(
    (result.matched_ingredients ?? []).map((item) => item.name.toLowerCase()),
  )
  const haveIngredients = scaled.ingredients.filter((ing) =>
    matchedNames.has(ing.name.toLowerCase()),
  )
  const missingIngredients = scaled.ingredients.filter(
    (ing) => !matchedNames.has(ing.name.toLowerCase()),
  )

  const rankingEntry = result.processing_trace
    ?.at(-1)
    ?.ranking.find((entry) => entry.recipe_id === recipeId)

  const iconCategory = deriveIconCategory(scaled.ingredients.map((ing) => ing.name))
  const dietaryMarks = deriveDietaryMarks(
    detail?.dietary_tags,
    scaled.ingredients.map((ing) => ing.name),
  )

  return (
    <div className="flex flex-col gap-8">
      <Ticket>
        <div className="flex items-start gap-6">
          <RecipeIcon category={iconCategory} size="large" />
          <div className="flex flex-1 flex-col gap-2">
            <h2 className="text-title text-ink-900">{scaled.name}</h2>
            <DietMarks marks={dietaryMarks} />
            <p className="text-body-lg text-ink-600">
              {scaled.cook_time_minutes ? `${scaled.cook_time_minutes} min` : 'Cook time unknown'}
              {scaled.cook_time_adjusted && scaled.cook_time_note
                ? ` (${scaled.cook_time_note})`
                : ''}
              {detail?.cuisine ? ` · ${detail.cuisine}` : ''} · scaled for {scaled.target_servings}{' '}
              serving{scaled.target_servings === 1 ? '' : 's'}
            </p>
            {rankingEntry && rankingEntry.match_score !== null && (
              <div className="flex items-center gap-2">
                <span className="font-mono text-body-lg text-ink-900">
                  {Math.round(rankingEntry.match_score * 100)}%
                </span>
                <span className="text-label text-steel-400">
                  {matchQualifier(rankingEntry.match_score)}
                </span>
                <Stamp signal={rankingEntry.can_cook ? 'positive' : 'negative'}>
                  {rankingEntry.can_cook ? 'cookable' : 'missing items'}
                </Stamp>
              </div>
            )}
            {rankingEntry && rankingEntry.match_score === null && (
              <Stamp signal={rankingEntry.can_cook ? 'positive' : 'negative'}>
                {rankingEntry.can_cook ? 'cookable' : 'missing items'}
              </Stamp>
            )}
          </div>
        </div>
      </Ticket>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div>
          <h3 className="text-heading text-ink-900">Ingredients</h3>
          <ul className="mt-2 flex flex-col gap-1">
            {haveIngredients.map((ing) => (
              <li
                key={ing.name}
                className="flex items-baseline gap-2 py-1 text-body-lg text-ink-900"
              >
                <span aria-hidden="true" className="text-signal-positive">
                  ✓
                </span>
                <span>
                  {ing.quantity_display}
                  {ing.unit ? ` ${ing.unit}` : ''} {ing.name}
                </span>
              </li>
            ))}
            {missingIngredients.map((ing) => (
              <li
                key={ing.name}
                className="flex items-baseline gap-2 py-1 text-body-lg text-steel-400"
              >
                <span aria-hidden="true">·</span>
                <span>
                  {ing.quantity_display}
                  {ing.unit ? ` ${ing.unit}` : ''} {ing.name}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h3 className="text-heading text-ink-900">Steps</h3>
          {detail?.steps ? (
            <ol className="mt-2 flex flex-col gap-4">
              {detail.steps.map((step, index) => (
                <li key={index} className="flex gap-3 text-body-lg text-ink-900">
                  <span className="font-mono text-ink-600">{index + 1}.</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          ) : detailError ? (
            <p className="mt-2 text-body-lg text-signal-negative">Couldn't load the steps.</p>
          ) : (
            <p className="mt-2 text-body-lg text-steel-400">Loading steps…</p>
          )}
        </div>
      </div>

      {result.nutrition_info && <NutritionPanel nutrition={result.nutrition_info} />}

      <ReasoningPanel
        reasoning={result.top_recommendation?.reasoning}
        overallSummary={result.top_recommendation?.overall_summary}
      />

      <MissingAndSubstitutions
        missingIngredients={missingIngredients.map((ing) => ({
          name: ing.name,
          importance: ing.importance,
        }))}
        substitutions={result.substitutions}
        groceryList={result.grocery_list}
      />

      <CookThis
        recipeId={recipeId}
        defaultServings={scaled.target_servings}
        cuisine={detail?.cuisine ?? null}
      />
    </div>
  )
}
