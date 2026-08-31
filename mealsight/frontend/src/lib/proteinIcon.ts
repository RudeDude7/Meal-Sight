import { matchesWholeWord } from '@/lib/wholeWordMatch'

/**
 * Mirrors mealsight/seed/recipe_parsing.py's own PROTEIN_TERMS and
 * mealsight/user_intelligence/scoring.py's own derive_protein() —
 * NOT a copy of the backend's real normalize_ingredient/synonym
 * pipeline (that's a DB-backed canonicalization table this frontend
 * has no access to), just a whole-word match against raw ingredient
 * names, which is enough to pick an icon category consistently with
 * what the backend already computes for the same recipe in the common
 * case.
 *
 * THESE TWO LISTS MUST STAY IN SYNC. If PROTEIN_TERMS in recipe_
 * parsing.py ever changes, update PROTEIN_TERMS below to match.
 */
export const PROTEIN_TERMS = [
  'chicken',
  'beef',
  'pork',
  'lamb',
  'turkey',
  'duck',
  'goat',
  'veal',
  'shrimp',
  'prawn',
  'fish',
  'salmon',
  'tuna',
  'cod',
  'crab',
  'lobster',
  'squid',
  'octopus',
  'bacon',
  'sausage',
  'ham',
  'tofu',
  'tempeh',
  'egg',
  'eggs',
  'beans',
  'chickpeas',
  'lentils',
  'paneer',
] as const

/**
 * "honey" is NOT one of the backend's own PROTEIN_TERMS — derive_
 * protein() would never return it, so a recipe using honey is never
 * backend-classified as protein-bearing because of it. The task's own
 * icon mapping table still asks for a bee icon on a honey-using
 * recipe, so this is a genuinely separate, frontend-only addition
 * checked BEFORE falling back to the real PROTEIN_TERMS list below —
 * not a silent claim that the backend already agrees with it.
 */
const FRONTEND_ONLY_EXTRA_TERMS = ['honey'] as const

export type IconCategory =
  'hen' | 'cow' | 'pig' | 'sheep' | 'fish' | 'egg' | 'bee' | 'legume' | 'leaf'

// Every real PROTEIN_TERMS word is covered here — including lobster/
// octopus/sausage/eggs, which the task's own mapping table didn't
// explicitly mention. Bucketed by the closest real-world grouping:
// lobster/octopus join the fish/seafood bucket, sausage joins pig
// (most commonly pork), eggs (plural) is just egg.
const TERM_TO_ICON: Record<
  (typeof PROTEIN_TERMS)[number] | (typeof FRONTEND_ONLY_EXTRA_TERMS)[number],
  IconCategory
> = {
  chicken: 'hen',
  turkey: 'hen',
  duck: 'hen',
  beef: 'cow',
  veal: 'cow',
  pork: 'pig',
  bacon: 'pig',
  ham: 'pig',
  sausage: 'pig',
  lamb: 'sheep',
  goat: 'sheep',
  fish: 'fish',
  salmon: 'fish',
  tuna: 'fish',
  cod: 'fish',
  shrimp: 'fish',
  prawn: 'fish',
  crab: 'fish',
  lobster: 'fish',
  squid: 'fish',
  octopus: 'fish',
  egg: 'egg',
  eggs: 'egg',
  honey: 'bee',
  tofu: 'legume',
  tempeh: 'legume',
  paneer: 'legume',
  beans: 'legume',
  chickpeas: 'legume',
  lentils: 'legume',
}

/**
 * Returns the icon category for a recipe, given its ingredient names
 * (in the recipe's own listed order — matching derive_protein's own
 * "first ingredient, in order, that matches" behavior) and its dietary
 * tags.
 *
 * Judgment call, documented rather than left implicit: protein-term
 * matching runs FIRST, regardless of dietary tags — a "vegetarian"-
 * tagged recipe that uses tofu still gets the more specific legume
 * icon, not a generic leaf, since that's more informative and the
 * task's own mapping table gives legumes their own explicit bucket.
 * The leaf fallback fires only when NO ingredient matches ANY known
 * protein term at all, which is what "vegetarian/vegan tagged" will
 * naturally resolve to in the common case anyway (a vegetarian recipe
 * usually has no chicken/beef/fish/etc. among its ingredients).
 */
export function deriveIconCategory(ingredientNames: string[]): IconCategory {
  const allTerms: readonly string[] = [...FRONTEND_ONLY_EXTRA_TERMS, ...PROTEIN_TERMS]
  for (const rawName of ingredientNames) {
    const name = rawName.trim().toLowerCase()
    for (const term of allTerms) {
      if (matchesWholeWord(name, term)) {
        return TERM_TO_ICON[term as keyof typeof TERM_TO_ICON]
      }
    }
  }
  return 'leaf'
}
