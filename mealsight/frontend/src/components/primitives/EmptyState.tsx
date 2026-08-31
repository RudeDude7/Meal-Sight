import emptyFridgeUrl from '@/assets/illustrations/empty-fridge.svg'
import emptyListPadUrl from '@/assets/illustrations/empty-list-pad.svg'
import emptySpikeUrl from '@/assets/illustrations/empty-spike.svg'

export type EmptyIllustration = 'fridge' | 'list-pad' | 'spike'

const ILLUSTRATION_URL: Record<EmptyIllustration, string> = {
  fridge: emptyFridgeUrl,
  'list-pad': emptyListPadUrl,
  spike: emptySpikeUrl,
}

interface EmptyStateProps {
  illustration: EmptyIllustration
  message: string
}

/**
 * The empty state every genuinely-empty collection page (Pantry,
 * Grocery List, History) uses — a single-weight ink-900 line-art
 * illustration (no fill, no color, no mascot, no face — matching
 * RecipeIcon's own visual family without borrowing its filled color
 * style) above one calm instruction line. Self-hosted SVGs, each a few
 * hundred bytes, stroked directly with the real ink-900 hex value
 * rather than currentColor: these render via a plain <img>, and an
 * externally-loaded SVG document is isolated from the parent page's
 * CSS (currentColor inside it would resolve to the SVG's own default,
 * not this app's ink-900) — confirmed by checking this directly rather
 * than assuming the usual CSS inheritance rule still applies across
 * that boundary.
 */
export function EmptyState({ illustration, message }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-sm border border-ink-900 bg-paper-raised px-6 py-12 text-center">
      <img
        src={ILLUSTRATION_URL[illustration]}
        alt=""
        aria-hidden="true"
        className="h-[120px] w-[120px]"
      />
      <p className="text-body-lg text-ink-600">{message}</p>
    </div>
  )
}
