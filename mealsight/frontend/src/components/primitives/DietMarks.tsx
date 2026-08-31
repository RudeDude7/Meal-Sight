import { useState } from 'react'

import type { DietaryMark, DietColorToken } from '@/lib/dietaryMarks'

const COLOR_BG: Record<DietColorToken, string> = {
  vegan: 'bg-diet-vegan',
  vegetarian: 'bg-diet-vegetarian',
  meat: 'bg-diet-meat',
  fish: 'bg-diet-fish',
  dairyfree: 'bg-diet-dairyfree',
  glutenfree: 'bg-diet-glutenfree',
  nutfree: 'bg-diet-nutfree',
}

interface DietMarkDotProps {
  mark: DietaryMark
}

/**
 * One mark: a plain filled circle plus a tooltip giving its full name.
 * Each of the seven now has its OWN diet-* color (no two share a
 * token), but the tooltip stays regardless — color is still only a
 * fast visual cue, never the sole way to identify a mark; anyone
 * relying on assistive tech or simply unsure of an exact hue still
 * gets the real name from aria-label and the tooltip text itself.
 *
 * TOOLTIP APPROACH, chosen deliberately over hover-only: the dot is a
 * real <button>, so it's keyboard-reachable by Tab and exposes its
 * full name via aria-label unconditionally (a screen reader announces
 * it regardless of whether the visual tooltip is showing at all). The
 * visual tooltip itself is shown on real :hover, on :focus-visible
 * (keyboard), AND on click/tap — the click/tap handler is what makes
 * this actually usable on a touch device, which has no meaningful
 * hover state to trigger a hover-only tooltip at all. Tapping again,
 * or the button losing focus, hides it. No extra library, no
 * hover-only trap.
 */
function DietMarkDot({ mark }: DietMarkDotProps) {
  const [tapped, setTapped] = useState(false)

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={mark.label}
        onClick={() => setTapped((current) => !current)}
        onBlur={() => setTapped(false)}
        className={[
          'group h-2.5 w-2.5 rounded-full',
          COLOR_BG[mark.color],
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-active focus-visible:outline-offset-2',
        ].join(' ')}
      >
        <span
          aria-hidden="true"
          className={[
            'pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap',
            'rounded-sm border border-ink-900 bg-paper-raised px-2 py-1 font-mono text-label text-ink-900',
            'transition-opacity',
            tapped
              ? 'opacity-100'
              : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100',
          ].join(' ')}
        >
          {mark.label}
        </span>
      </button>
    </span>
  )
}

interface DietMarksProps {
  marks: DietaryMark[]
}

/**
 * A row of small filled circles, one per dietary property that
 * actually applies to a recipe — see src/lib/dietaryMarks.ts for the
 * full derivation logic and, critically, the safety constraint on
 * what this component is allowed to ever assert. Renders nothing at
 * all when no marks apply — there is no "absent"/greyed-out dot,
 * matching the same "don't guess, don't fake it" rule RecipeIcon and
 * the Ticket's own empty states already follow.
 */
export function DietMarks({ marks }: DietMarksProps) {
  if (marks.length === 0) return null

  return (
    <div className="flex items-center gap-2">
      {marks.map((mark) => (
        <DietMarkDot key={mark.id} mark={mark} />
      ))}
    </div>
  )
}
