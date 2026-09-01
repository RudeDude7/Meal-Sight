import { useState } from 'react'

import { Button } from '@/components/primitives/Button'
import { Well } from '@/components/primitives/Well'
import { PANTRY_CATEGORIES } from '@/lib/pantryCategories'
import type { PantryItemInput } from '@/types/pantry'

interface AddPantryItemFormProps {
  onAdd: (item: PantryItemInput) => Promise<void>
}

/**
 * Manually adding an item needs a category — the backend derives
 * estimated_shelf_days from it (mealsight/pantry/shelf_life.py's own
 * resolve_shelf_life), so leaving it out wouldn't just be an incomplete
 * form field, it would mean this item never gets a real days_remaining
 * at all. Category is therefore required here, not optional.
 */
export function AddPantryItemForm({ onAdd }: AddPantryItemFormProps) {
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('')
  const [category, setCategory] = useState<string>(PANTRY_CATEGORIES[0])
  const [submitting, setSubmitting] = useState(false)

  const canSubmit = name.trim().length > 0 && !submitting

  async function handleSubmit(): Promise<void> {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      await onAdd({
        name: name.trim(),
        quantity: quantity.trim() ? Number(quantity) : null,
        unit: unit.trim() || null,
        category,
      })
      setName('')
      setQuantity('')
      setUnit('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Well className="flex flex-wrap items-end gap-3 p-4">
      <label className="flex flex-col gap-1">
        <span className="text-label text-ink-600">Item</span>
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. flour"
          className="w-40 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-label text-ink-600">Quantity</span>
        <input
          type="number"
          min={0}
          step="any"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-label text-ink-600">Unit</span>
        <input
          type="text"
          value={unit}
          onChange={(event) => setUnit(event.target.value)}
          placeholder="optional"
          className="w-24 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-label text-ink-600">Category</span>
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          className="rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
        >
          {PANTRY_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </label>
      <Button variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
        {submitting ? 'Adding…' : 'Add item'}
      </Button>
    </Well>
  )
}
