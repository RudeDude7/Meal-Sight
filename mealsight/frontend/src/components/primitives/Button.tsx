import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'bg-ink-900 text-paper-0 hover:bg-ink-600',
  secondary: 'border border-ink-900 text-ink-900 hover:bg-paper-1',
  ghost: 'text-ink-600 hover:text-ink-900',
}

/**
 * The only three buttons this system allows: primary (one per view, the
 * single most important action), secondary (an outlined alternative
 * action), ghost (a low-emphasis action with no container of its own —
 * Remove/Cancel/Try again -style). Every button in the app is one of
 * these three variants; there is no fourth.
 */
export function Button({
  variant = 'secondary',
  type = 'button',
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={[
        'rounded-sm px-4 py-2 text-body-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        VARIANT_CLASS[variant],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    />
  )
}
