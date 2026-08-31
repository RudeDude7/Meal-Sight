export interface StripProps {
  /** Already-formatted, monospace-ready timestamp text (e.g. elapsed seconds, a clock time). */
  timestamp: string
  message: string
  /**
   * Plays the "printing in" entrance once, on mount — the literal
   * ticket-rail metaphor for a message that just genuinely arrived.
   * Defaults to true (a live loading view's own normal case); pass
   * false for a Strip rendered as part of an already-settled, static
   * history (present.py's own processing_trace shown after the fact,
   * for instance) — a Strip that was never actually "just now" must
   * never replay an arrival animation it didn't have.
   */
  animateIn?: boolean
}

/**
 * One line of the horizontal progress/log element the design system
 * calls a Strip: a monospace timestamp on the left, the message itself
 * on the right — used for the agent's own eleven-step pipeline and for
 * any future async process's own live log. Deliberately plain markup,
 * no card chrome of its own; a list of Strips is meant to read as one
 * continuous printed log, not a stack of separate boxes.
 */
export function Strip({ timestamp, message, animateIn = true }: StripProps) {
  return (
    <div
      className={[
        'flex items-baseline gap-3 border-b border-ink-900/10 px-1 py-2 last:border-b-0',
        animateIn && 'animate-strip-print-in',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span className="shrink-0 font-mono text-label text-steel-400">{timestamp}</span>
      <span className="text-body text-ink-900">{message}</span>
    </div>
  )
}
