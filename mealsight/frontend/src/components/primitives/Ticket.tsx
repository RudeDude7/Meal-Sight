import { forwardRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'

export type TicketPadding = 'default' | 'compact'

interface TicketProps {
  children: ReactNode
  padding?: TicketPadding
  /**
   * Interactive Tickets get the paper-hover fill on hover and the
   * standard focus outline, and are reachable by keyboard (Enter/
   * Space triggers onActivate, matching native button semantics).
   * Static Tickets get neither — a Ticket that isn't actually
   * clickable should never look or behave like it might be.
   */
  interactive?: boolean
  onActivate?: () => void
  className?: string
}

const PADDING_CLASS: Record<TicketPadding, string> = {
  default: 'p-6',
  compact: 'p-4',
}

/**
 * The core card primitive: paper-raised fill, a 1px ink-900 border on
 * all four edges, radius-sm on all four corners. Nothing more.
 *
 * The serrated top edge (a CSS mask-image) was tried and removed after
 * visual review of /preview — it read as an unfinished effect rather
 * than a torn ticket. Removing it also resolved two real, verified
 * problems the mask caused as a side effect: it clipped the top-inset
 * image's own overflow, and it clipped the focus outline on an
 * interactive Ticket into total invisibility (not just at the top —
 * the ENTIRE outline disappeared, since the mask's solid-fill layer
 * was sized exactly to the border box, and an outline paints outside
 * it). A plain four-sided border has neither problem.
 */
export const Ticket = forwardRef<HTMLDivElement, TicketProps>(function Ticket(
  { children, padding = 'default', interactive = false, onActivate, className },
  ref,
) {
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (!interactive || !onActivate) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onActivate()
    }
  }

  return (
    <div
      ref={ref}
      className={[
        'rounded-sm border border-ink-900 bg-paper-raised',
        interactive &&
          'cursor-pointer transition-colors hover:bg-paper-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-active focus-visible:outline-offset-2',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? 'button' : undefined}
      onClick={interactive ? onActivate : undefined}
      onKeyDown={handleKeyDown}
    >
      <div className={PADDING_CLASS[padding]}>{children}</div>
    </div>
  )
})
