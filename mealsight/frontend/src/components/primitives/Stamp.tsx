export type StampSignal = 'active' | 'positive' | 'negative' | 'info'

interface StampProps {
  signal: StampSignal
  children: string
}

const SIGNAL_STYLES: Record<StampSignal, string> = {
  active: 'border-signal-active text-signal-active',
  positive: 'border-signal-positive text-signal-positive',
  negative: 'border-signal-negative text-signal-negative',
  info: 'border-signal-info text-signal-info',
}

/**
 * The status-badge primitive: radius-pill, 2px border, one of the four
 * signal colors, always upright at 0 degrees. Rotation was tried
 * (deterministic, hashed from content) and removed after visual review
 * of /preview — across a real list it read as inconsistent rather than
 * characterful, not the intended effect. Every Stamp sits flat now.
 */
export function Stamp({ signal, children }: StampProps) {
  return (
    <span
      className={[
        'inline-flex items-center rounded-pill border-2 bg-paper-raised px-3 py-1',
        'font-mono text-label font-medium leading-none',
        SIGNAL_STYLES[signal],
      ].join(' ')}
    >
      {children}
    </span>
  )
}
