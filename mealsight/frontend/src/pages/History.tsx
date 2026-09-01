import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { getHistory } from '@/api/history'
import { getInteractions } from '@/api/interactions'
import { PageError } from '@/components/common/PageError'
import { PageLoading } from '@/components/common/PageLoading'
import { EmptyState } from '@/components/primitives/EmptyState'
import { InteractionTicket } from '@/components/history/InteractionTicket'
import { MealHistoryTicket } from '@/components/history/MealHistoryTicket'
import type { InteractionRecord, MealHistoryEntry } from '@/types/profile'

type Tab = 'meals' | 'requests'

/**
 * Two record kinds, presented as TABS rather than a merged timeline or
 * stacked sections. Reasoning: they support genuinely different
 * actions (a meal can be rated, an interaction never can — there's
 * nothing to rate about a request that didn't lead to a cook), and they
 * carry very different information density (a meal is a few fields; an
 * interaction can carry a full transcript and a full final_response
 * paragraph). Interleaving both by date into one scroll would force a
 * reader to context-switch between "what did I cook" and "what did I
 * ask for" on every single card. Two tabs let each list be read on its
 * own terms, most recent first within each — merging them would also
 * have meant inventing a shared sort/display shape for two records that
 * don't actually share one.
 */
export function History() {
  const [tab, setTab] = useState<Tab>('meals')
  const [meals, setMeals] = useState<MealHistoryEntry[] | null>(null)
  const [interactions, setInteractions] = useState<InteractionRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [historyResponse, interactionsResponse] = await Promise.all([
        getHistory(),
        getInteractions(),
      ])
      setMeals(historyResponse.meals)
      setInteractions(interactionsResponse.interactions)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your history.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading && meals === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">History</h1>
        <div className="mt-6">
          <PageLoading label="Loading your history…" />
        </div>
      </section>
    )
  }

  if (error && meals === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">History</h1>
        <div className="mt-6">
          <PageError message={error} onRetry={() => void load()} />
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">History</h1>

      <div className="mt-4 flex gap-1 border-b border-ink-900/10">
        <button
          type="button"
          onClick={() => setTab('meals')}
          className={[
            'border-b-2 px-4 py-2 text-body-lg font-medium',
            tab === 'meals'
              ? 'border-signal-active text-signal-active'
              : 'border-transparent text-ink-600 hover:text-ink-900',
          ].join(' ')}
        >
          Meals cooked
        </button>
        <button
          type="button"
          onClick={() => setTab('requests')}
          className={[
            'border-b-2 px-4 py-2 text-body-lg font-medium',
            tab === 'requests'
              ? 'border-signal-active text-signal-active'
              : 'border-transparent text-ink-600 hover:text-ink-900',
          ].join(' ')}
        >
          Requests
        </button>
      </div>

      <div className="mt-6">
        {tab === 'meals' &&
          (meals && meals.length > 0 ? (
            <div className="flex flex-col gap-3">
              {meals.map((meal) => (
                <MealHistoryTicket key={meal.id} meal={meal} />
              ))}
            </div>
          ) : (
            <EmptyState illustration="spike" message="No meals logged yet." />
          ))}

        {tab === 'requests' &&
          (interactions && interactions.length > 0 ? (
            <div className="flex flex-col gap-3">
              {interactions.map((interaction) => (
                <InteractionTicket key={interaction.id} interaction={interaction} />
              ))}
            </div>
          ) : (
            <EmptyState
              illustration="spike"
              message="No recommendation requests yet — ask Home for a recommendation and it'll show up here."
            />
          ))}
      </div>
    </section>
  )
}
