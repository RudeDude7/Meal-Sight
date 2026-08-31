import { matchesWholeWord } from '@/lib/wholeWordMatch'

/**
 * FINDING, verified by reading mealsight/seed/recipe_parsing.py's own
 * derive_dietary_tags() directly rather than trusting mealsight/db/
 * schema/recipes.sql's own comment (which shows a HYPHENATED example,
 * ["vegetarian", "gluten-free"] — that comment is stale/wrong relative
 * to the real generation code): the tags a recipe's own dietary_tags
 * field actually contains are "vegetarian", "vegan", "dairy_free",
 * "gluten_free", "nut_free" — single words or UNDERSCORE-separated,
 * never hyphenated. (A completely separate vocabulary, mealsight.
 * perception.dietary's own DIETARY_RESTRICTION_VOCABULARY, IS
 * hyphenated — "dairy-free", "gluten-free" — but that's for what a
 * USER said they want, a different concept entirely from what a
 * RECIPE is tagged with.) Matching below accepts both forms anyway,
 * defensively, in case that inconsistency is ever "fixed" by changing
 * the wrong side.
 *
 * SECOND FINDING: derive_dietary_tags() appends "vegetarian" and
 * "vegan" INDEPENDENTLY (an is_meat_free check for the former, a
 * separate is_meat_free-and-dairy_free-and-egg_free-and-honey_free
 * check for the latter) — a vegan recipe's real dietary_tags contains
 * BOTH "vegetarian" AND "vegan" simultaneously. The mutual-exclusivity
 * this module enforces (vegan wins, vegetarian is suppressed) is
 * therefore not a hypothetical edge case; it is the ordinary shape of
 * the real data for every vegan recipe this backend has ever tagged.
 */
function normalizeTag(tag: string): string {
  return tag.trim().toLowerCase().replace(/-/g, '_')
}

/**
 * "meat" and "fish" are curated subsets of mealsight/seed/recipe_
 * parsing.py's own real MEAT_TERMS blocklist (used there to decide
 * vegetarian/vegan, not exposed as separate tags) — NOT the same list
 * as src/lib/proteinIcon.ts's PROTEIN_TERMS (a different backend list,
 * derive_protein's own, used for icon selection, which doesn't include
 * "anchovy" at all and buckets meat+fish together by animal rather
 * than splitting them). All three lists are real and backend-derived;
 * they simply serve three different purposes and were never meant to
 * be identical to each other. This split (task-specified) is exactly
 * the subset needed to make two SEPARATE, more specific assertions
 * ("contains meat" vs. "contains fish") than the backend's own single
 * combined vegetarian/vegan check makes.
 */
const MEAT_MARK_TERMS = [
  'chicken',
  'beef',
  'pork',
  'lamb',
  'turkey',
  'duck',
  'goat',
  'veal',
  'bacon',
  'ham',
  'sausage',
]
const FISH_MARK_TERMS = [
  'fish',
  'salmon',
  'tuna',
  'cod',
  'shrimp',
  'prawn',
  'crab',
  'lobster',
  'squid',
  'anchovy',
]

export type DietaryMarkId =
  | 'vegan'
  | 'vegetarian'
  | 'contains-meat'
  | 'contains-fish'
  | 'dairy-free'
  | 'gluten-free'
  | 'nut-free'

// Each mark gets its OWN diet-* color (tailwind.config.cjs) — no two
// of the seven share a token anymore, unlike the earlier signal-*
// based version where dairy-free/gluten-free/nut-free were all
// signal-info and indistinguishable by color alone. See that config
// file's own comment for why this is a separate palette from signal-*
// rather than signal-* extended further.
export type DietColorToken =
  'vegan' | 'vegetarian' | 'meat' | 'fish' | 'dairyfree' | 'glutenfree' | 'nutfree'

export interface DietaryMark {
  id: DietaryMarkId
  label: string
  color: DietColorToken
}

// Fixed display order, regardless of which subset actually applies to
// a given recipe — matches the order the task itself listed them in.
const MARK_DEFINITIONS: Record<DietaryMarkId, { label: string; color: DietColorToken }> = {
  vegan: { label: 'Vegan', color: 'vegan' },
  vegetarian: { label: 'Vegetarian', color: 'vegetarian' },
  'contains-meat': { label: 'Contains meat', color: 'meat' },
  'contains-fish': { label: 'Contains fish', color: 'fish' },
  'dairy-free': { label: 'Dairy-free', color: 'dairyfree' },
  'gluten-free': { label: 'Gluten-free', color: 'glutenfree' },
  'nut-free': { label: 'Nut-free', color: 'nutfree' },
}

function mark(id: DietaryMarkId): DietaryMark {
  return { id, ...MARK_DEFINITIONS[id] }
}

/**
 * CRITICAL SAFETY CONSTRAINT — read before changing anything here.
 *
 * The backend derives dietary_tags CONSERVATIVELY: a tag is applied
 * only when every ingredient is confidently clear of the relevant
 * blocklist (see recipe_parsing.py's own "Every term list below is
 * intentionally a blocklist, not an allowlist" comment). This means
 * the ABSENCE of, say, a "nut_free" tag asserts NOTHING — a genuinely
 * nut-free recipe can easily carry no nut_free tag at all, simply
 * because one ingredient's name wasn't recognized. The absence is
 * silence, not a negative result.
 *
 * Consequently this function must NEVER render a mark meaning
 * "contains nuts", "contains dairy", or "contains gluten" — there is
 * no data anywhere in this system that actually supports that claim
 * (the backend only ever computes the FREE-of-X side, conservatively,
 * never an explicit CONTAINS-X side for nuts/dairy/gluten), and a
 * fabricated one could genuinely harm someone with an allergy who
 * trusts it. Only positive assertions are ever rendered: vegan/
 * vegetarian/dairy-free/gluten-free/nut-free (all "this recipe has
 * this property," backed by a real backend tag), and contains-meat/
 * contains-fish (backed by an actual protein-term match in the
 * recipe's own ingredients, not by the absence of a tag — which is
 * exactly why these two, unlike a hypothetical "contains-nuts", are
 * safe to assert at all).
 */
export function deriveDietaryMarks(
  dietaryTags: string[] | undefined | null,
  ingredientNames: string[],
): DietaryMark[] {
  const tags = new Set((dietaryTags ?? []).map(normalizeTag))
  const marks: DietaryMark[] = []

  // Mutually exclusive: see this module's own "SECOND FINDING" above —
  // a vegan recipe's real tags contain BOTH words, so vegan must be
  // checked first and vegetarian suppressed when it's present.
  if (tags.has('vegan')) {
    marks.push(mark('vegan'))
  } else if (tags.has('vegetarian')) {
    marks.push(mark('vegetarian'))
  }

  const normalizedIngredients = ingredientNames.map((name) => name.trim().toLowerCase())
  const hasMeat = normalizedIngredients.some((name) =>
    MEAT_MARK_TERMS.some((term) => matchesWholeWord(name, term)),
  )
  const hasFish = normalizedIngredients.some((name) =>
    FISH_MARK_TERMS.some((term) => matchesWholeWord(name, term)),
  )
  if (hasMeat) marks.push(mark('contains-meat'))
  if (hasFish) marks.push(mark('contains-fish'))

  if (tags.has('dairy_free')) marks.push(mark('dairy-free'))
  if (tags.has('gluten_free')) marks.push(mark('gluten-free'))
  if (tags.has('nut_free')) marks.push(mark('nut-free'))

  return marks
}
