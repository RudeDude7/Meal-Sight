import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { deletePantryItem, getExpiringPantryItems, getPantry, updatePantry } from '@/api/pantry'
import { logWaste } from '@/api/waste'
import { PageError } from '@/components/common/PageError'
import { PageLoading } from '@/components/common/PageLoading'
import { Button } from '@/components/primitives/Button'
import { EmptyState } from '@/components/primitives/EmptyState'
import { Ticket } from '@/components/primitives/Ticket'
import { AddPantryItemForm } from '@/components/pantry/AddPantryItemForm'
import { PantryItemRow } from '@/components/pantry/PantryItemRow'
import { isStale } from '@/lib/pantryStatus'
import type { ExpiringItem, PantryItem, PantryItemInput } from '@/types/pantry'

function canonicalKey(name: string): string {
  return name.trim().toLowerCase()
}

/** Expired and expiring both outrank a plain fresh item; stale is its own, lower-urgency tier. */
function sortPriority(expiring: ExpiringItem | undefined, stale: boolean): number {
  if (expiring && expiring.days_remaining < 0) return 0
  if (expiring) return 1
  if (stale) return 2
  return 3
}

export function Pantry() {
  const [items, setItems] = useState<PantryItem[] | null>(null)
  const [expiring, setExpiring] = useState<ExpiringItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // Set only right after a "Throw out" action, from log_waste's own
  // real insight text (mealsight.pantry.waste) — never client-invented
  // copy. The row that triggered it is gone by the time this renders
  // (log_waste always removes the full quantity), so the insight has
  // to live at the page level to be visible at all.
  const [wasteInsight, setWasteInsight] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [pantryResponse, expiringResponse] = await Promise.all([
        getPantry(),
        getExpiringPantryItems(),
      ])
      setItems(pantryResponse.items)
      setExpiring(expiringResponse.items)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your pantry.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleAdjustQuantity(item: PantryItem, newQuantity: number): Promise<void> {
    // PATCH /api/pantry's own update_pantry ALWAYS adds the given
    // quantity to whatever's already there (see mealsight/pantry/
    // update.py's own module docstring: "quantity ADDED... never
    // replaced") — there is no set-to-X operation on this endpoint.
    // Sending the DELTA, not the target value, is what makes "adjust
    // to N" work against an add-only endpoint. freshness_status is
    // passed back as the item's own current value so a plain quantity
    // edit never silently resets it to the default "fresh".
    const delta = newQuantity - (item.quantity ?? 0)
    const payload: PantryItemInput = {
      name: item.name,
      quantity: delta,
      unit: item.unit,
      category: item.category,
      freshness_status: item.freshness_status,
    }
    await updatePantry([payload])
    await load()
  }

  async function handleRemove(item: PantryItem): Promise<void> {
    await deletePantryItem(item.id)
    await load()
  }

  async function handleWasteItem(item: PantryItem): Promise<void> {
    // The full quantity, not a partial one: "throw out" on an expired
    // row means the whole thing is gone, the same way this page's own
    // Remove already treats a delete as "all of it" (deletePantryItem
    // resolves to remove_items with the item's full current quantity).
    const result = await logWaste({
      item_name: item.name,
      quantity_wasted: item.quantity ?? 0,
      unit: item.unit,
      reason: 'expired',
    })
    setWasteInsight(result.insight)
    await load()
  }

  async function handleAdd(item: PantryItemInput): Promise<void> {
    await updatePantry([item])
    await load()
  }

  if (loading && items === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Pantry</h1>
        <div className="mt-6">
          <PageLoading label="Loading your pantry…" />
        </div>
      </section>
    )
  }

  if (error && items === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Pantry</h1>
        <div className="mt-6">
          <PageError message={error} onRetry={() => void load()} />
        </div>
      </section>
    )
  }

  const expiringByName = new Map(expiring.map((item) => [canonicalKey(item.name), item]))

  const sortedItems = [...(items ?? [])].sort((a, b) => {
    const aExpiring = expiringByName.get(canonicalKey(a.name))
    const bExpiring = expiringByName.get(canonicalKey(b.name))
    const aStale = !aExpiring && isStale(a.last_seen_date)
    const bStale = !bExpiring && isStale(b.last_seen_date)
    const aPriority = sortPriority(aExpiring, aStale)
    const bPriority = sortPriority(bExpiring, bStale)
    if (aPriority !== bPriority) return aPriority - bPriority
    const aDays = a.days_remaining ?? Number.POSITIVE_INFINITY
    const bDays = b.days_remaining ?? Number.POSITIVE_INFINITY
    if (aDays !== bDays) return aDays - bDays
    return a.name.localeCompare(b.name)
  })

  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Pantry</h1>

      {wasteInsight && (
        <div className="mt-6">
          <Ticket padding="compact" className="border-signal-info">
            <div className="flex items-start justify-between gap-4">
              <p className="text-body-lg text-ink-900">{wasteInsight}</p>
              <Button variant="ghost" onClick={() => setWasteInsight(null)}>
                Dismiss
              </Button>
            </div>
          </Ticket>
        </div>
      )}

      {sortedItems.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            illustration="fridge"
            message="Your pantry is empty. Add a photo of your fridge or shelves to get started."
          />
        </div>
      ) : (
        <div className="mt-6 flex flex-col gap-3">
          {sortedItems.map((item) => (
            <PantryItemRow
              key={item.id}
              item={item}
              expiring={expiringByName.get(canonicalKey(item.name))}
              onAdjustQuantity={handleAdjustQuantity}
              onRemove={handleRemove}
              onWaste={handleWasteItem}
            />
          ))}
        </div>
      )}

      <div className="mt-8">
        <AddPantryItemForm onAdd={handleAdd} />
      </div>
    </section>
  )
}
