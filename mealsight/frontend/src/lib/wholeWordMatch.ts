/**
 * Whole-word containment, not raw substring containment — the same
 * discipline mealsight.matching.normalize / mealsight.seed.recipe_
 * parsing use on the backend, and for the identical reason: a raw
 * `term in name` check would let "egg" match inside "reggiano". Shared
 * here since both src/lib/proteinIcon.ts and src/lib/dietaryMarks.ts
 * need the identical check against their own, different term lists.
 *
 * ALSO tolerates a trailing "s"/"es" on the matched word — e.g. a term
 * list entry of "prawn" still matches the ingredient name "prawns".
 * FOUND LIVE, not assumed: a real screenshot-driven check of /preview
 * showed "Raw king prawns" producing no "contains fish" mark at all,
 * because the backend's own real normalize_ingredient singularizes
 * ingredient names before matching (mealsight.matching.normalize, a
 * whole pipeline this frontend has no access to) and this mirror,
 * without that step, was comparing the literal plural "prawns" against
 * the singular term "prawn" and finding no word-boundary match at all
 * ("prawn" and "prawns" have no boundary between the shared "n" and
 * the trailing "s"). This is a deliberately simple approximation of
 * that same normalization, not a full port of it.
 */
export function matchesWholeWord(name: string, term: string): boolean {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`\\b${escaped}(?:es|s)?\\b`).test(name)
}
