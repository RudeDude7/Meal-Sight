import { NavLink, Outlet } from 'react-router-dom'

const NAV_LINKS: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Home', end: true },
  { to: '/pantry', label: 'Pantry' },
  { to: '/profile', label: 'Profile' },
]

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return [
    'rounded-card px-3 py-2 text-body font-medium transition-colors',
    isActive
      ? 'bg-brand-100 text-brand-800'
      : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
  ].join(' ')
}

export function NavShell() {
  return (
    <div className="min-h-screen bg-surface-subtle">
      <header className="border-b border-ink/5 bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <span className="text-title text-brand-700">MealSight</span>
          <nav className="flex items-center gap-1">
            {NAV_LINKS.map((link) => (
              <NavLink key={link.to} to={link.to} end={link.end} className={navLinkClassName}>
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
