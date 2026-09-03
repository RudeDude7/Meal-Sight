import { useState } from 'react'

import { Button } from '@/components/primitives/Button'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { daysSinceLastSeen, isStale } from '@/lib/pantryStatus'
import type { ExpiringItem, PantryItem } from '@/types/pantry'

interface PantryItemRowProps {
  item: PantryItem
  /** Matched from GET /api/pantry/expiring by canonical name, when this item is on that list at all. */
  expiring: ExpiringItem | undefined
  onAdjustQuantity: (item: PantryItem, newQuantity: number) => Promise<void>
  onRemove: (item: PantryItem) => Promise<void>
  /**
   * Logs the item as wasted (reason "expired") and deducts it from the
   * pantry in the same call — see api/waste.ts / mealsight.pantry.waste.
   * log_waste's own real insight text (once one exists) is the parent's
   * concern, not this row's: logging waste always removes the full
   * quantity, so this row unmounts the moment the parent reloads —
   * nothing rendered here would survive long enough to be read.
   */
  onWaste: (item: PantryItem) => Promise<void>
}

/**
 * One pantry row: a compact (16px) Ticket. Expiry is this page's own
 * reason to exist, so the state pattern is decided in a fixed priority
 * — EXPIRED (negative) beats EXPIRING (active) beats STALE (info,
 * partial/caveat) beats a plain fresh item with no Stamp at all. Expired
 * and expiring both come from the real backend list (GET /api/pantry/
 * expiring, this session's own addition — see that endpoint's own
 * comment for why it exists) rather than a client-recomputed threshold;
 * stale is computed client-side from last_seen_date, a single fixed-
 * threshold comparison with no drift-prone table behind it (see
 * src/lib/pantryStatus.ts).
 *
 * "Throw out" (waste tracking) only appears on an EXPIRED item — the
 * backend already flags it, and "throw this out" is the honest next
 * action for something already past its estimated shelf life, so this
 * is the one row state that offers it. A fresh or merely-expiring-soon
 * item keeps only the existing plain Remove action; Remove and Throw
 * out both end up deducting the pantry row, but only Throw out records
 * WHY, which is what feeds get_waste_stats' own insights.
 */
export function PantryItemRow({ item, expiring, onAdjustQuantity, onRemove, onWaste }: PantryItemRowProps) {
  const [quantityDraft, setQuantityDraft] = useState(String(item.quantity ?? ''))
  const [saving, setSaving] = useState(false)
  const [confirmingRemove, setConfirmingRemove] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [confirmingWaste, setConfirmingWaste] = useState(false)
  const [wasting, setWasting] = useState(false)

  const stale = isStale(item.last_seen_date)
  const expired = expiring !== undefined && expiring.days_remaining < 0
  const expiringSoon = expiring !== undefined && expiring.days_remaining >= 0

  const draftChanged = quantityDraft !== String(item.quantity ?? '')

  async function handleSaveQuantity(): Promise<void> {
    const parsed = Number(quantityDraft)
    if (Number.isNaN(parsed) || parsed < 0) return
    setSaving(true)
    try {
      await onAdjustQuantity(item, parsed)
    } finally {
      setSaving(false)
    }
  }

  async function handleConfirmRemove(): Promise<void> {
    setRemoving(true)
    try {
      await onRemove(item)
    } finally {
      setRemoving(false)
      setConfirmingRemove(false)
    }
  }

  async function handleConfirmWaste(): Promise<void> {
    setWasting(true)
    try {
      await onWaste(item)
    } finally {
      setWasting(false)
      setConfirmingWaste(false)
    }
  }

  return (
    <Ticket padding="compact">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-body-lg capitalize text-ink-900">{item.name}</span>
            {expired && <Stamp signal="negative">expired</Stamp>}
            {expiringSoon && <Stamp signal="active">expiring soon</Stamp>}
            {!expiring && stale && <Stamp signal="info">unsure if still have</Stamp>}
          </div>
          <p className="text-label text-steel-400">
            {item.category}
            {item.days_remaining !== null
              ? ` · ${item.days_remaining < 0 ? `${Math.abs(item.days_remaining)}d overdue` : `${item.days_remaining}d left`}`
              : ''}
          </p>
          {/* The backend's own real suggested_action copy — never
              rewritten here, per this page's own explicit instruction. */}
          {expiring && <p className="text-label text-ink-600">{expiring.suggested_action}</p>}
          {!expiring && stale && (
            <p className="text-label text-signal-info">
              Not seen in the pantry for {daysSinceLastSeen(item.last_seen_date)} days — worth
              checking it's still there.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            step="any"
            value={quantityDraft}
            onChange={(event) => setQuantityDraft(event.target.value)}
            disabled={saving || removing || wasting}
            className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-2 py-1 text-body-lg text-ink-900"
            aria-label={`Quantity for ${item.name}`}
          />
          <span className="text-label text-steel-400">{item.unit ?? ''}</span>

          {draftChanged && (
            <Button variant="secondary" onClick={handleSaveQuantity} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          )}

          {expired && !confirmingWaste && !confirmingRemove && (
            <Button
              variant="ghost"
              className="text-signal-negative hover:text-signal-negative"
              onClick={() => setConfirmingWaste(true)}
            >
              Throw out
            </Button>
          )}

          {confirmingWaste && (
            <div className="flex items-center gap-2">
              <span className="text-label text-ink-600">Log as wasted (expired) and remove it?</span>
              <Button
                variant="secondary"
                className="border-signal-negative text-signal-negative hover:bg-signal-negative/10"
                onClick={handleConfirmWaste}
                disabled={wasting}
              >
                {wasting ? 'Logging…' : 'Yes, throw out'}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmingWaste(false)} disabled={wasting}>
                Cancel
              </Button>
            </div>
          )}

          {!confirmingWaste && !confirmingRemove ? (
            <Button
              variant="ghost"
              className="text-signal-negative hover:text-signal-negative"
              onClick={() => setConfirmingRemove(true)}
            >
              Remove
            </Button>
          ) : confirmingRemove ? (
            <div className="flex items-center gap-2">
              <span className="text-label text-ink-600">Remove this item?</span>
              <Button
                variant="secondary"
                className="border-signal-negative text-signal-negative hover:bg-signal-negative/10"
                onClick={handleConfirmRemove}
                disabled={removing}
              >
                {removing ? 'Removing…' : 'Yes, remove'}
              </Button>
              <Button
                variant="ghost"
                onClick={() => setConfirmingRemove(false)}
                disabled={removing}
              >
                Cancel
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </Ticket>
  )
}
