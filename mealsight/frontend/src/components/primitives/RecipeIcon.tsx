import type { IconCategory } from '@/lib/proteinIcon'

import beeUrl from '@/assets/icons/bee.svg'
import cookingUrl from '@/assets/icons/cooking.svg'
import cowUrl from '@/assets/icons/cow.svg'
import eggUrl from '@/assets/icons/egg.svg'
import fishUrl from '@/assets/icons/fish.svg'
import henUrl from '@/assets/icons/hen.svg'
import leafUrl from '@/assets/icons/leaf.svg'
import legumeUrl from '@/assets/icons/legume.svg'
import pigUrl from '@/assets/icons/pig.svg'
import sheepUrl from '@/assets/icons/sheep.svg'

// 'loading' is NOT one of proteinIcon.ts's own IconCategory values —
// it isn't a real, derived category at all, just this component's own
// placeholder for "which recipe this is is still unknown, the agent
// hasn't decided yet." Kept local to RecipeIcon rather than added to
// IconCategory so that type stays exactly what it says: real,
// protein-derived categories a finished recipe actually has.
export type RecipeIconCategory = IconCategory | 'loading'

const ICON_URL: Record<RecipeIconCategory, string> = {
  hen: henUrl,
  cow: cowUrl,
  pig: pigUrl,
  sheep: sheepUrl,
  fish: fishUrl,
  egg: eggUrl,
  bee: beeUrl,
  legume: legumeUrl,
  leaf: leafUrl,
  loading: cookingUrl,
}

const ICON_LABEL: Record<RecipeIconCategory, string> = {
  hen: 'Poultry',
  cow: 'Beef',
  pig: 'Pork',
  sheep: 'Lamb or goat',
  fish: 'Seafood',
  egg: 'Egg',
  bee: 'Honey',
  legume: 'Legume',
  leaf: 'Vegetarian',
  loading: 'Preparing your recommendation',
}

export type RecipeIconSize = 'default' | 'large'

const CONTAINER_SIZE: Record<RecipeIconSize, string> = {
  default: 'h-20 w-20',
  large: 'h-32 w-32',
}
const IMAGE_SIZE: Record<RecipeIconSize, number> = {
  default: 40,
  large: 64,
}

interface RecipeIconProps {
  category: RecipeIconCategory
  /**
   * Gentle idle motion while a recommendation is actually being
   * computed — the ONE case this design system permits motion at all
   * ("animate only when something is genuinely, currently happening").
   * false (the default) is what a finished, rendered recipe card
   * always uses: a permanently-animating icon on a settled result
   * would break that rule. Wired into LoadingView (category="loading",
   * animated, size="large") for the real loading showpiece.
   */
  animated?: boolean
  size?: RecipeIconSize
  className?: string
}

/**
 * The Ticket's visual anchor where a TheMealDB photo used to be — a
 * self-hosted vector icon chosen from the recipe's primary protein
 * (src/lib/proteinIcon.ts), never a hotlinked photo. TheMealDB images
 * are inconsistent in quality, frequently absent, and reintroduce the
 * food-blog aesthetic this system exists to reject; a fixed, self-
 * hosted icon set never has that problem and never needs a network
 * request of its own.
 */
export function RecipeIcon({
  category,
  animated = false,
  size = 'default',
  className,
}: RecipeIconProps) {
  return (
    <div
      className={[
        'flex items-center justify-center rounded-sm bg-paper-1',
        CONTAINER_SIZE[size],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <img
        src={ICON_URL[category]}
        alt={ICON_LABEL[category]}
        width={IMAGE_SIZE[size]}
        height={IMAGE_SIZE[size]}
        className={animated ? 'animate-icon-idle' : undefined}
      />
    </div>
  )
}
