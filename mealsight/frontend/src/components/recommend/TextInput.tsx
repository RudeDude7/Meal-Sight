import { useId } from 'react'

import { MAX_TEXT_LENGTH } from '@/lib/inputLimits'

interface TextInputProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export function TextInput({ value, onChange, disabled = false }: TextInputProps) {
  const textareaId = useId()
  const remaining = MAX_TEXT_LENGTH - value.length
  const overLimit = remaining < 0

  return (
    <div>
      <label htmlFor={textareaId} className="text-subtitle text-ink">
        Or just describe it
      </label>
      <textarea
        id={textareaId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder="e.g. I have chicken thighs, rice, and some vegetables, want something quick"
        rows={3}
        maxLength={MAX_TEXT_LENGTH + 200}
        className="mt-3 w-full rounded-card border border-ink/10 bg-surface p-3 text-body text-ink placeholder:text-ink-faint focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
      />
      <p className={`mt-1 text-caption ${overLimit ? 'text-danger-600' : 'text-ink-faint'}`}>
        {overLimit
          ? `${Math.abs(remaining)} characters over the ${MAX_TEXT_LENGTH} limit`
          : `${value.length} / ${MAX_TEXT_LENGTH}`}
      </p>
    </div>
  )
}
