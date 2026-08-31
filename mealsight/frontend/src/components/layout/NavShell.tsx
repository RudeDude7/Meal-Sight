import { NavLink, Outlet } from 'react-router-dom'
import type { ComponentType } from 'react'

import {
  GroceryListIcon,
  HistoryIcon,
  HomeIcon,
  PantryIcon,
  ProfileIcon,
} from '@/components/layout/NavIcons'
import { useActiveSession } from '@/lib/activeSessionContext'

interface NavItem {
  to: string
  label: string
  end?: boolean
  Icon: ComponentType<{ className?: string }>
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Home', end: true, Icon: HomeIcon },
  { to: '/pantry', label: 'Pantry', Icon: PantryIcon },
  { to: '/grocery-list', label: 'Grocery List', Icon: GroceryListIcon },
  { to: '/history', label: 'History', Icon: HistoryIcon },
  { to: '/profile', label: 'Profile', Icon: ProfileIcon },
]

/**
 * Formats the masthead's own ticket number. A real trace_id (the same
 * id mealsight/api/routers/recommend.py returns as session_id, and the
 * agent run uses as its own trace_id) is shown, uppercased and
 * truncated to a ticket-length 8 characters, while a run is actually
 * in flight. Idle shows a stable placeholder of dashes at the same
 * width — never a fake id that LOOKS like a real one. This is the
 * literal application of the system's own honesty principle to a
 * decorative-looking corner of the UI: a masthead detail is still
 * visible data, and visible data must be true data.
 */
function formatTicketNumber(traceId: string | null): string {
  if (!traceId) return '————————'
  return traceId.replace(/-/g, '').slice(0, 8).toUpperCase()
}

/**
 * The persistent left rail — 240px with icon + label above 1024px,
 * icon-only at 64px between 768 and 1024px, hidden entirely below
 * 768px (BottomTabBar takes over there instead). The active item gets a
 * 3px signal-active bar on the rail's own left edge — the vertical
 * equivalent of a Ticket's own border weight, not a background fill,
 * so it reads as a physical marker on the rail rather than a hover
 * state that stuck.
 */
function Rail() {
  return (
    <nav
      aria-label="Primary"
      className="sticky top-14 hidden h-[calc(100vh-56px)] w-16 shrink-0 flex-col gap-1 overflow-y-auto border-r border-ink-900/10 bg-paper-raised py-4 md:flex lg:w-[240px]"
    >
      {NAV_ITEMS.map(({ to, label, end, Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            [
              'flex items-center gap-3 border-l-[3px] px-4 py-3 text-body-lg font-medium transition-colors',
              isActive
                ? 'border-signal-active bg-signal-active/10 text-signal-active'
                : 'border-transparent text-ink-600 hover:bg-paper-1 hover:text-ink-900',
            ].join(' ')
          }
        >
          <Icon className="h-6 w-6 shrink-0" />
          <span className="hidden lg:inline">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

/**
 * Below 768px the rail becomes a fixed bottom tab bar, 56px, icon plus
 * label per item — never a hamburger (the system's own explicit rule:
 * every destination stays one tap away, nothing goes behind a menu).
 * A left-edge bar makes no sense on a horizontal bar, so the active
 * item instead gets the same 3px signal-active bar moved to its TOP
 * edge — the edge that actually faces the content above it, keeping
 * the same weight and color as the rail's own indicator so it still
 * reads as the same system, just rotated to fit a different edge.
 */
function BottomTabBar() {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-20 flex h-14 border-t border-ink-900 bg-paper-raised md:hidden"
    >
      {NAV_ITEMS.map(({ to, label, end, Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            [
              'flex flex-1 flex-col items-center justify-center gap-1 border-t-[3px] text-[11px] font-medium transition-colors',
              isActive
                ? 'border-signal-active text-signal-active'
                : 'border-transparent text-ink-600',
            ].join(' ')
          }
        >
          <Icon className="h-4 w-4" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export function NavShell() {
  const { traceId } = useActiveSession()

  return (
    <div className="min-h-screen bg-paper-0">
      {/* h-14/top-14/pt-14 (56px) throughout this shell, and the rail's
          own 240px, are spec-mandated structural chrome dimensions, not
          spacing debt — the same category of fixed exception as
          Stamp's 2px border or fontSize's own closed scale, outside the
          4-point spacing scale's jurisdiction on purpose. */}
      <header className="fixed inset-x-0 top-0 z-30 h-14 bg-paper-raised">
        <div className="flex h-full items-center justify-between px-6">
          <span className="text-title text-ink-900">MealSight</span>
          <span className="font-mono text-label text-ink-600">
            NO. {formatTicketNumber(traceId)}
          </span>
        </div>
        {/* The printed rule beneath the masthead proper — a real 2px
            ink-900 line, not the faint 5%-opacity divider a generic app
            bar would use, so it reads as the header rule on an order
            pad rather than a subtle UI seam. */}
        <div className="border-b-2 border-ink-900" />
      </header>

      {/* auto / 1fr / 0px: the rail sizes to its own content, the main
          column takes the rest, and the right slot exists in the grid
          from day one at 0px — activating it later (a detail panel, a
          future feature) becomes a width transition on an already-real
          grid track instead of a layout restructure. */}
      <div className="grid grid-cols-[auto_1fr_0px] pt-14">
        <Rail />
        <main className="min-h-[calc(100vh-56px)] w-full min-w-0 px-6 py-8 pb-16 md:pb-8">
          {/* w-full + max-w-[960px] IS min(960px, available space) — at
              exactly 1024px, 240px rail + a rigid 960px block would
              overflow; this shrinks with the viewport instead. */}
          <div className="mx-auto w-full max-w-[960px]">
            <Outlet />
          </div>
        </main>
        <aside aria-hidden="true" className="w-0 overflow-hidden" />
      </div>

      <BottomTabBar />
    </div>
  )
}
