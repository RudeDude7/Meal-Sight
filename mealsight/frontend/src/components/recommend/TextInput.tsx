import { useId } from 'react'

import { Well } from '@/components/primitives/Well'
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
      <label htmlFor={textareaId} className="text-heading text-ink-900">
        Or just describe it
      </label>
      <Well className="mt-3">
        <textarea
          id={textareaId}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          placeholder="e.g. I have chicken thighs, rice, and some vegetables, want something quick"
          rows={3}
          maxLength={MAX_TEXT_LENGTH + 200}
          className="w-full bg-transparent p-3 text-body-lg text-ink-900 placeholder:text-steel-400 focus:outline-none disabled:opacity-50"
        />
      </Well>
      <p className={`mt-1 text-label ${overLimit ? 'text-signal-negative' : 'text-steel-400'}`}>
        {overLimit
          ? `${Math.abs(remaining)} characters over the ${MAX_TEXT_LENGTH} limit`
          : `${value.length} / ${MAX_TEXT_LENGTH}`}
      </p>
    </div>
  )
}
