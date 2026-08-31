interface NavIconProps {
  className?: string
}

// Five nav-rail icons, hand-authored to match RecipeIcon/EmptyState's own
// visual family: single-weight stroke, no fill, no color baked in.
// Inline JSX (not self-hosted <img> assets like RecipeIcon/EmptyState)
// deliberately — an externally-loaded SVG's currentColor does not
// inherit the parent document's color (a real bug caught and fixed
// earlier this project, see EmptyState's own history), and these icons
// specifically need to inherit the rail item's active/inactive text
// color, not carry a fixed one of their own.

const STROKE_PROPS = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export function HomeIcon({ className }: NavIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...STROKE_PROPS} aria-hidden="true">
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6 10v9h12v-9" />
      <path d="M10 19v-5h4v5" />
    </svg>
  )
}

export function PantryIcon({ className }: NavIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...STROKE_PROPS} aria-hidden="true">
      <rect x="6" y="3" width="12" height="18" rx="1" />
      <line x1="6" y1="10" x2="18" y2="10" />
      <line x1="9" y1="6" x2="9" y2="8" />
      <line x1="9" y1="13" x2="9" y2="15" />
    </svg>
  )
}

export function ProfileIcon({ className }: NavIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...STROKE_PROPS} aria-hidden="true">
      <circle cx="12" cy="8.5" r="3.25" />
      <path d="M5.5 20c0-3.6 2.9-6.25 6.5-6.25S18.5 16.4 18.5 20" />
    </svg>
  )
}

export function GroceryListIcon({ className }: NavIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...STROKE_PROPS} aria-hidden="true">
      <rect x="5" y="3" width="14" height="18" rx="1" />
      <line x1="8" y1="8" x2="16" y2="8" />
      <line x1="8" y1="12" x2="16" y2="12" />
      <line x1="8" y1="16" x2="13" y2="16" />
    </svg>
  )
}

export function HistoryIcon({ className }: NavIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...STROKE_PROPS} aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7.5V12l3.5 2" />
    </svg>
  )
}
