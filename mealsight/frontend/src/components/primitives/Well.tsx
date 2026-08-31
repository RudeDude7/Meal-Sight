import type { ReactNode } from 'react'

interface WellProps {
  children: ReactNode
  className?: string
}

/**
 * The recessed-container primitive: paper-1 fill, an inset shadow only
 * (shadow-well — see tailwind.config.cjs's own boxShadow comment for why
 * that's the one outer-elevation exception this system allows). Reads as
 * a surface pressed IN, the opposite of a Ticket, which is always raised
 * above the base. Used for input containers — a drop zone, a recorder
 * area, a textarea — anywhere the app is asking to receive something
 * rather than presenting something back.
 */
export function Well({ children, className }: WellProps) {
  return (
    <div className={['rounded-sm bg-paper-1 shadow-well', className].filter(Boolean).join(' ')}>
      {children}
    </div>
  )
}
