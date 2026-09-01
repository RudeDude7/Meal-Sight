import { useState } from 'react'

import { Button } from '@/components/primitives/Button'
import { Well } from '@/components/primitives/Well'

interface PreferenceListEditorProps {
  label: string
  hint: string
  items: string[]
  onAdd: (value: string) => Promise<void>
  onRemove: (value: string) => Promise<void>
}

/**
 * dietary_restrictions and disliked_ingredients are lists, not a text
 * blob — add and remove one entry at a time, matching how the backend
 * itself treats them (additive on write, a separate removal path). The
 * backend canonicalizes disliked_ingredients through the exact same
 * normalize_ingredient + synonym pipeline pantry items go through — a
 * typed "scallions" rendering back as "green onion" afterward is that
 * pipeline working correctly, not a bug, so this deliberately shows
 * whatever the server actually stored rather than echoing back the
 * raw typed text.
 */
export function PreferenceListEditor({
  label,
  hint,
  items,
  onAdd,
  onRemove,
}: PreferenceListEditorProps) {
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [removingValue, setRemovingValue] = useState<string | null>(null)

  async function handleAdd(): Promise<void> {
    const trimmed = draft.trim()
    if (!trimmed || submitting) return
    setSubmitting(true)
    try {
      await onAdd(trimmed)
      setDraft('')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRemove(value: string): Promise<void> {
    setRemovingValue(value)
    try {
      await onRemove(value)
    } finally {
      setRemovingValue(null)
    }
  }

  return (
    <div>
      <h3 className="text-heading text-ink-900">{label}</h3>
      <p className="mt-1 text-label text-steel-400">{hint}</p>

      <div className="mt-3 flex flex-wrap gap-2">
        {items.length === 0 && <span className="text-label text-steel-400">None yet.</span>}
        {items.map((item) => (
          <span
            key={item}
            className="flex items-center gap-2 rounded-sm border border-ink-900/10 bg-paper-1 px-3 py-1 text-body-lg capitalize text-ink-900"
          >
            {item}
            <button
              type="button"
              onClick={() => void handleRemove(item)}
              disabled={removingValue === item}
              aria-label={`Remove ${item}`}
              className="text-steel-400 hover:text-signal-negative"
            >
              ×
            </button>
          </span>
        ))}
      </div>

      <Well className="mt-3 flex items-center gap-2 p-2">
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void handleAdd()
          }}
          placeholder="Add an item"
          disabled={submitting}
          className="flex-1 bg-transparent px-2 py-1 text-body-lg text-ink-900 placeholder:text-steel-400 focus:outline-none"
        />
        <Button
          variant="secondary"
          onClick={() => void handleAdd()}
          disabled={submitting || !draft.trim()}
        >
          Add
        </Button>
      </Well>
    </div>
  )
}
