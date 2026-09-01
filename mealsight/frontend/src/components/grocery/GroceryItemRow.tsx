import type { GroceryListItem } from '@/types/pantry'

interface GroceryItemRowProps {
  item: GroceryListItem
  checked: boolean
  onToggle: () => void
}

function formatQuantities(item: GroceryListItem): string {
  const parts = item.quantities
    .filter((q) => q.quantity !== null)
    .map((q) => `${q.quantity}${q.unit ? ` ${q.unit}` : ''}`)
  return parts.join(' + ')
}

export function GroceryItemRow({ item, checked, onToggle }: GroceryItemRowProps) {
  const quantityText = formatQuantities(item)

  return (
    <li className="flex items-start gap-3 py-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 h-4 w-4 shrink-0 accent-signal-active"
        aria-label={`Checked off: ${item.name}`}
      />
      <div className="flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span
            className={[
              'text-body-lg capitalize',
              checked ? 'text-steel-400 line-through' : 'text-ink-900',
            ].join(' ')}
          >
            {item.name}
            {quantityText ? ` — ${quantityText}` : ''}
          </span>
          <span className="text-label text-steel-400">{item.importance}</span>
        </div>
        {item.needed_for.length > 0 && (
          <p className="text-label text-steel-400">for {item.needed_for.join(', ')}</p>
        )}
        {/* The backend's own real verify_note copy — never rewritten here. */}
        {item.is_staple && item.verify_note && (
          <p className="text-label text-signal-info">{item.verify_note}</p>
        )}
      </div>
    </li>
  )
}
