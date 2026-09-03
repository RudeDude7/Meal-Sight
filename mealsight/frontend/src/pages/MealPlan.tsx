import { useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { createMealPlan } from '@/api/mealPlan'
import { PageError } from '@/components/common/PageError'
import { Button } from '@/components/primitives/Button'
import { EmptyState } from '@/components/primitives/EmptyState'
import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { GroceryItemRow } from '@/components/grocery/GroceryItemRow'
import type { MealPlanResult } from '@/types/mealPlan'

function useElapsedSeconds(startedAt: number | null): number {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (startedAt === null) return
    setElapsed((Date.now() - startedAt) / 1000)
    // Same 100ms tick as recommend/LoadingView.tsx's own timer — fine
    // enough to visibly move every frame, cheap enough to cost nothing
    // over a real multi-second planning run.
    const interval = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 100)
    return () => clearInterval(interval)
  }, [startedAt])

  return elapsed
}

/**
 * Planning evaluates many more candidates than a single recommendation
 * (match_ingredients called once per candidate in the pool, not once
 * per short list — see mealsight.agent.meal_planner's own module
 * docstring) and takes noticeably longer. No message stream exists for
 * this synchronous POST (unlike /api/recommend's own WebSocket), so
 * this reuses only the live-timer half of recommend/LoadingView.tsx's
 * own pattern, not its Strip-printing half.
 */
function PlanningLoadingView({ startedAt }: { startedAt: number }) {
  const elapsedSeconds = useElapsedSeconds(startedAt)
  return (
    <div className="flex flex-col items-center gap-6 rounded-sm border border-ink-900 bg-paper-raised p-8">
      <RecipeIcon category="loading" animated size="large" />
      <div className="font-mono text-title tabular-nums text-signal-active" aria-live="polite">
        {elapsedSeconds.toFixed(1)}s
      </div>
      <p className="text-body-lg text-ink-600">
        Evaluating candidate recipes across the week — this takes longer than a single
        recommendation.
      </p>
    </div>
  )
}

function DayCard({ day }: { day: MealPlanResult['days'][number] }) {
  return (
    <Ticket>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-label text-steel-400">Day {day.day_index + 1}</p>
          <h3 className="text-heading text-ink-900">{day.recipe_name}</h3>
          <p className="mt-1 text-label text-steel-400">
            {day.cuisine ?? 'cuisine unknown'}
            {day.protein_type ? ` · ${day.protein_type}` : ''} · {day.servings} serving
            {day.servings === 1 ? '' : 's'}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {day.can_cook ? (
            <Stamp signal="active">can cook</Stamp>
          ) : (
            <Stamp signal="negative">missing items</Stamp>
          )}
          {day.cuisine_repeat_forced && <Stamp signal="info">cuisine repeated</Stamp>}
        </div>
      </div>

      {day.uses_expiring_ingredient_names.length > 0 && (
        <p className="mt-3 text-label text-signal-active">
          Uses expiring: {day.uses_expiring_ingredient_names.join(', ')}
        </p>
      )}

      {day.missing_ingredient_names.length > 0 && (
        <div className="mt-3">
          <p className="text-label text-ink-600">Need to buy:</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {day.missing_ingredient_names.map((name) => {
              const shared = day.shared_missing_ingredient_names.includes(name)
              return (
                <li
                  key={name}
                  className={[
                    'rounded-sm border px-2 py-0.5 text-label',
                    shared
                      ? 'border-signal-active text-signal-active'
                      : 'border-ink-900/10 text-ink-600',
                  ].join(' ')}
                  title={shared ? 'Also needed by an earlier day this week' : undefined}
                >
                  {name}
                  {shared ? ' ↺' : ''}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </Ticket>
  )
}

export function MealPlan() {
  const [days, setDays] = useState('5')
  const [servings, setServings] = useState('2')
  const [dietaryText, setDietaryText] = useState('')
  const [avoidText, setAvoidText] = useState('')
  const [maxCookTime, setMaxCookTime] = useState('')

  const [loading, setLoading] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [result, setResult] = useState<MealPlanResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [unsatisfiable, setUnsatisfiable] = useState<string | null>(null)

  async function handleGenerate(): Promise<void> {
    setLoading(true)
    setError(null)
    setUnsatisfiable(null)
    setResult(null)
    const start = Date.now()
    setStartedAt(start)
    try {
      const plan = await createMealPlan({
        days: Number(days) || 5,
        servings: Number(servings) || 2,
        dietary_restrictions: dietaryText
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        avoid_ingredients: avoidText
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        max_cook_time_minutes: maxCookTime.trim() ? Number(maxCookTime) : undefined,
      })
      setResult(plan)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'plan_unsatisfiable') {
        setUnsatisfiable(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not generate a meal plan.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Meal Plan</h1>
      <p className="mt-2 text-body-lg text-ink-600">
        A day-by-day plan built to reuse what's already in your pantry, use up what's expiring
        soon, and minimize how many new ingredients you have to buy.
      </p>

      <div className="mt-6 flex flex-wrap items-end gap-3 rounded-sm bg-paper-1 p-4 shadow-well">
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Days</span>
          <input
            type="number"
            min={1}
            value={days}
            onChange={(event) => setDays(event.target.value)}
            disabled={loading}
            className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Servings</span>
          <input
            type="number"
            min={1}
            value={servings}
            onChange={(event) => setServings(event.target.value)}
            disabled={loading}
            className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Max cook time (min)</span>
          <input
            type="number"
            min={1}
            placeholder="optional"
            value={maxCookTime}
            onChange={(event) => setMaxCookTime(event.target.value)}
            disabled={loading}
            className="w-32 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Dietary restrictions</span>
          <input
            type="text"
            placeholder="e.g. vegetarian, gluten_free"
            value={dietaryText}
            onChange={(event) => setDietaryText(event.target.value)}
            disabled={loading}
            className="w-56 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-label text-ink-600">Avoid ingredients</span>
          <input
            type="text"
            placeholder="e.g. peanuts, shellfish"
            value={avoidText}
            onChange={(event) => setAvoidText(event.target.value)}
            disabled={loading}
            className="w-56 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
          />
        </label>
        <Button variant="primary" onClick={() => void handleGenerate()} disabled={loading}>
          {loading ? 'Planning…' : 'Generate plan'}
        </Button>
      </div>

      <div className="mt-6">
        {loading && startedAt !== null && <PlanningLoadingView startedAt={startedAt} />}

        {!loading && unsatisfiable && (
          <PageError
            message={`Couldn't build a plan with these constraints: ${unsatisfiable}`}
            onRetry={() => void handleGenerate()}
          />
        )}

        {!loading && error && <PageError message={error} onRetry={() => void handleGenerate()} />}

        {!loading && !result && !error && !unsatisfiable && (
          <EmptyState
            illustration="list-pad"
            message="Set your days and servings above, then generate a plan."
          />
        )}

        {!loading && result && (
          <div className="flex flex-col gap-6">
            <Ticket padding="compact">
              <p className="text-body-lg text-ink-900">
                <strong>{result.total_distinct_ingredients}</strong> distinct ingredient
                {result.total_distinct_ingredients === 1 ? '' : 's'} to buy this week —{' '}
                <strong>{result.shared_ingredient_count}</strong> of those{' '}
                {result.shared_ingredient_count === 1 ? 'is' : 'are'} shared across more than one
                day, so nothing extra gets bought for them twice.
              </p>
              <p className="mt-1 text-label text-steel-400">
                Generated in {result.wall_clock_seconds.toFixed(1)}s.
              </p>
            </Ticket>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {result.days.map((day) => (
                <DayCard key={day.day_index} day={day} />
              ))}
            </div>

            <div>
              <h2 className="text-heading text-ink-900">Weekly nutrition</h2>
              <p className="mt-1 text-label text-steel-400">
                {result.nutrition_summary.coverage_note}
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-body-lg text-ink-900 sm:grid-cols-3">
                <div>
                  <dt className="text-label text-steel-400">Calories</dt>
                  <dd>{result.nutrition_summary.total_calories.toFixed(0)}</dd>
                </div>
                <div>
                  <dt className="text-label text-steel-400">Protein</dt>
                  <dd>{result.nutrition_summary.total_protein_g.toFixed(0)}g</dd>
                </div>
                <div>
                  <dt className="text-label text-steel-400">Carbs</dt>
                  <dd>{result.nutrition_summary.total_carbs_g.toFixed(0)}g</dd>
                </div>
                <div>
                  <dt className="text-label text-steel-400">Fat</dt>
                  <dd>{result.nutrition_summary.total_fat_g.toFixed(0)}g</dd>
                </div>
                <div>
                  <dt className="text-label text-steel-400">Fiber</dt>
                  <dd>{result.nutrition_summary.total_fiber_g.toFixed(0)}g</dd>
                </div>
                <div>
                  <dt className="text-label text-steel-400">Sodium</dt>
                  <dd>{result.nutrition_summary.total_sodium_mg.toFixed(0)}mg</dd>
                </div>
              </dl>
            </div>

            {result.grocery_list && result.grocery_list.sections.length > 0 && (
              <div>
                <h2 className="text-heading text-ink-900">Consolidated grocery list</h2>
                {/* Same section-grouping GroceryList.tsx itself uses —
                    reused directly, not a second aggregator, matching
                    the backend's own create_grocery_list reuse. */}
                <div className="mt-2 flex flex-col gap-4">
                  {result.grocery_list.sections.map((section) => (
                    <Ticket key={section.section}>
                      <h3 className="text-heading capitalize text-ink-900">{section.section}</h3>
                      <ul className="mt-2 flex flex-col divide-y divide-ink-900/10">
                        {section.items.map((item) => (
                          <GroceryItemRow key={item.name} item={item} checked={false} onToggle={() => {}} />
                        ))}
                      </ul>
                    </Ticket>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
