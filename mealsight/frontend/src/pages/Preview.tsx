import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { DietMarks } from '@/components/primitives/DietMarks'
import { EmptyState } from '@/components/primitives/EmptyState'
import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { LoadingView } from '@/components/recommend/LoadingView'
import type { LoadingStrip } from '@/components/recommend/LoadingView'
import { useBatchedList } from '@/hooks/useBatchedList'
import { deriveDietaryMarks } from '@/lib/dietaryMarks'
import type { DietaryMark } from '@/lib/dietaryMarks'
import { deriveIconCategory } from '@/lib/proteinIcon'
import type { IconCategory } from '@/lib/proteinIcon'

function PreviewSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-heading text-ink-900">{title}</h2>
      {children}
    </section>
  )
}

const ALL_CATEGORIES: IconCategory[] = [
  'hen',
  'cow',
  'pig',
  'sheep',
  'fish',
  'egg',
  'bee',
  'legume',
  'leaf',
]

// Real ingredient lists (Chicken Enchilada Casserole is the exact real
// data used in this project's own live backend verification earlier)
// run through the actual deriveIconCategory function below, not
// hardcoded — proving the mapping logic itself, not just the icon set.
const RECIPE_EXAMPLES: {
  name: string
  ingredients: string[]
  dietaryTags: string[]
}[] = [
  {
    name: 'Chicken Enchilada Casserole',
    ingredients: [
      'Enchilada sauce',
      'shredded Monterey Jack cheese',
      'corn tortillas',
      'chicken breasts',
    ],
    dietaryTags: [],
  },
  {
    name: 'Garides Saganaki',
    ingredients: ['Raw king prawns', 'Olive oil', 'White wine', 'Feta cheese'],
    dietaryTags: [],
  },
  {
    name: 'Chana Masala',
    ingredients: ['Chickpeas', 'Onion', 'Tomato', 'Garam masala'],
    dietaryTags: ['vegetarian'],
  },
  {
    name: 'Garden Salad',
    ingredients: ['Lettuce', 'Cucumber', 'Tomato', 'Red onion'],
    dietaryTags: ['vegetarian'],
  },
]

// Three cases the task itself asked for: many marks, a single mark,
// and none at all — real dietaryTags/ingredients run through the
// actual deriveDietaryMarks function, not hardcoded mark lists.
const DIETARY_MARK_EXAMPLES: {
  name: string
  ingredients: string[]
  dietaryTags: string[]
}[] = [
  {
    name: 'Coconut Chickpea Curry (many marks)',
    ingredients: ['Chickpeas', 'Coconut milk', 'Rice', 'Cilantro'],
    dietaryTags: ['vegan', 'dairy_free', 'gluten_free', 'nut_free'],
  },
  {
    name: 'Roasted Pepper Rice (single mark)',
    ingredients: ['Rice', 'Roasted red pepper', 'Garlic', 'Olive oil'],
    dietaryTags: ['gluten_free'],
  },
  {
    name: 'Grandma’s Recipe (no marks apply)',
    ingredients: ['A pinch of this', 'A pinch of that'],
    dietaryTags: [],
  },
]

// One of each — enumerated directly (mirrors src/lib/dietaryMarks.ts's
// own MARK_DEFINITIONS) since no single real recipe naturally carries
// all seven at once (vegan suppresses vegetarian; contains-meat and
// contains-fish would never both apply to a vegan/vegetarian recipe).
// This is purely for the greyscale-distinguishability check the task
// itself asked for.
const ALL_SEVEN_MARKS: DietaryMark[] = [
  { id: 'vegan', label: 'Vegan', color: 'vegan' },
  { id: 'vegetarian', label: 'Vegetarian', color: 'vegetarian' },
  { id: 'contains-meat', label: 'Contains meat', color: 'meat' },
  { id: 'contains-fish', label: 'Contains fish', color: 'fish' },
  { id: 'dairy-free', label: 'Dairy-free', color: 'dairyfree' },
  { id: 'gluten-free', label: 'Gluten-free', color: 'glutenfree' },
  { id: 'nut-free', label: 'Nut-free', color: 'nutfree' },
]

interface ScheduledMessage {
  delayMs: number
  timestamp: string
  message: string
}

// The real measured pacing from actual runs (see this project's own
// phase 7.2/8.2 notes): step one (validate_input) completes in 0.14ms;
// perceive runs ~11s with a heartbeat every 3.0s; the remaining eight
// steps complete in ~150ms combined; ten recipe_match messages arrive
// in a 74ms burst near the end. This schedule reproduces that shape
// with simulated setTimeouts — not a real WebSocket — specifically so
// the loading view's own burst-batching can be judged against the
// actual pacing it has to survive, not an idealized even trickle.
const LOADING_DEMO_SCHEDULE: ScheduledMessage[] = [
  { delayMs: 0, timestamp: '+0.0s', message: '[validate_input] Got usable input.' },
  { delayMs: 1, timestamp: '+0.0s', message: '[validate_input] Done (0.14ms).' },
  { delayMs: 5, timestamp: '+0.0s', message: '[perceive] Analyzing your photo...' },
  { delayMs: 3000, timestamp: '+3.0s', message: '[perceive] Still analyzing your photo...' },
  { delayMs: 6000, timestamp: '+6.0s', message: '[perceive] Still working through the photo...' },
  {
    delayMs: 9000,
    timestamp: '+9.0s',
    message: '[perceive] The vision model is still looking closely...',
  },
  { delayMs: 11000, timestamp: '+11.0s', message: '[perceive] Found 12 item(s) in your photo.' },
  { delayMs: 11020, timestamp: '+11.0s', message: '[merge] Combined your inputs.' },
  { delayMs: 11040, timestamp: '+11.0s', message: '[update_pantry] Pantry updated.' },
  { delayMs: 11060, timestamp: '+11.1s', message: '[get_context] Looks like dinner time.' },
  { delayMs: 11080, timestamp: '+11.1s', message: '[search_recipes] Found 83 matching recipe(s).' },
  { delayMs: 11100, timestamp: '+11.1s', message: '[match_rank] Matching against your pantry...' },
  // The 74ms burst: ten recipe_match messages, ~7ms apart.
  ...Array.from({ length: 10 }, (_, index) => ({
    delayMs: 11105 + index * 7,
    timestamp: '+11.1s',
    message: `[match_rank] Candidate ${index + 1}/10 scored.`,
  })),
  {
    delayMs: 11180,
    timestamp: '+11.2s',
    message: '[reason] Recommending: Chicken Enchilada Casserole.',
  },
  {
    delayMs: 11190,
    timestamp: '+11.2s',
    message: '[generate_output] Prepared your recommendation.',
  },
  { delayMs: 11200, timestamp: '+11.2s', message: '[record_outcome] Recorded.' },
  { delayMs: 11210, timestamp: '+11.2s', message: '[present] Done — recommendation ready.' },
]

// Safely exceeds the measured 74ms burst window (see useBatchedList's
// own docstring) — every one of the ten recipe_match messages above
// lands inside a single flush, not ten.
const LOADING_DEMO_BATCH_WINDOW_MS = 80

function LoadingDemo() {
  const [strips, push] = useBatchedList<LoadingStrip>(LOADING_DEMO_BATCH_WINDOW_MS)
  const [startedAt] = useState(() => Date.now())
  const [running, setRunning] = useState(true)

  useEffect(() => {
    const timers = LOADING_DEMO_SCHEDULE.map((entry, index) =>
      setTimeout(
        () => push({ id: index, timestamp: entry.timestamp, message: entry.message }),
        entry.delayMs,
      ),
    )
    const finishTimer = setTimeout(() => setRunning(false), 11400)
    return () => {
      timers.forEach(clearTimeout)
      clearTimeout(finishTimer)
    }
    // Runs once on mount — this is a fixed demo schedule, not live data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!running) {
    return (
      <div className="rounded-sm border border-ink-900 bg-paper-raised p-8 text-center">
        <p className="text-body-lg text-ink-900">
          Done — nothing here animates once the run completes. This view is now static.
        </p>
      </div>
    )
  }

  return <LoadingView startedAt={startedAt} strips={strips} />
}

export function Preview() {
  const focusedTicketRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    focusedTicketRef.current?.focus()
  }, [])

  return (
    <div className="flex flex-col gap-12 bg-paper-0 p-8">
      <div>
        <h1 className="text-title text-ink-900">Ticket + Stamp preview</h1>
        <p className="mt-2 text-body-lg text-ink-600">
          Not linked from navigation — this route exists purely for visual judgment before these
          primitives are applied anywhere else.
        </p>
      </div>

      <PreviewSection title="Ticket — all-round border, several widths">
        <div className="flex flex-col gap-6">
          <div style={{ width: 320 }}>
            <Ticket>
              <p className="text-body-lg text-ink-900">Chicken Enchilada Casserole</p>
              <p className="mt-1 text-label text-steel-400">45 min · Mexican</p>
            </Ticket>
          </div>
          <div className="w-full">
            <Ticket>
              <p className="text-body-lg text-ink-900">Chicken Enchilada Casserole</p>
              <p className="mt-1 text-label text-steel-400">45 min · Mexican</p>
            </Ticket>
          </div>
          <div style={{ width: 960, maxWidth: '100%' }}>
            <Ticket>
              <p className="text-body-lg text-ink-900">Chicken Enchilada Casserole</p>
              <p className="mt-1 text-label text-steel-400">45 min · Mexican</p>
            </Ticket>
          </div>
        </div>
      </PreviewSection>

      <PreviewSection title="Padding: default (24px) vs. compact (16px)">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <Ticket padding="default">
            <p className="text-label text-steel-400">Default padding</p>
            <p className="mt-1 text-body-lg text-ink-900">Bakewell Tart</p>
          </Ticket>
          <Ticket padding="compact">
            <p className="text-label text-steel-400">Compact padding</p>
            <p className="mt-1 text-body-lg text-ink-900">Bakewell Tart</p>
          </Ticket>
        </div>
      </PreviewSection>

      <PreviewSection title="Recipe cards — RecipeIcon + DietMarks, derived from real ingredients">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {RECIPE_EXAMPLES.map((recipe) => {
            const category = deriveIconCategory(recipe.ingredients)
            const marks = deriveDietaryMarks(recipe.dietaryTags, recipe.ingredients)
            return (
              <Ticket key={recipe.name}>
                <div className="flex items-start gap-4">
                  <RecipeIcon category={category} />
                  <div>
                    <p className="text-body-lg text-ink-900">{recipe.name}</p>
                    <p className="mt-1 font-mono text-label text-steel-400">
                      icon: {category} · ingredients: {recipe.ingredients.join(', ')}
                    </p>
                    <div className="mt-2">
                      <DietMarks marks={marks} />
                    </div>
                  </div>
                </div>
              </Ticket>
            )
          })}
        </div>
      </PreviewSection>

      <PreviewSection title="Every icon in the mapping table">
        <div className="grid grid-cols-3 gap-6 sm:grid-cols-5">
          {ALL_CATEGORIES.map((category) => (
            <div key={category} className="flex flex-col items-center gap-2">
              <RecipeIcon category={category} />
              <span className="font-mono text-label text-steel-400">{category}</span>
            </div>
          ))}
        </div>
      </PreviewSection>

      <PreviewSection title="RecipeIcon — animated (loading) vs. static (settled result)">
        <div className="flex items-center gap-8">
          <div className="flex flex-col items-center gap-2">
            <RecipeIcon category="hen" animated />
            <span className="text-label text-steel-400">animated — while working</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <RecipeIcon category="hen" />
            <span className="text-label text-steel-400">static — settled result</span>
          </div>
        </div>
      </PreviewSection>

      <PreviewSection title="DietMarks — many marks, a single mark, and none at all">
        <div className="flex flex-col gap-4">
          {DIETARY_MARK_EXAMPLES.map((recipe) => {
            const marks = deriveDietaryMarks(recipe.dietaryTags, recipe.ingredients)
            return (
              <Ticket key={recipe.name} padding="compact">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-body-lg text-ink-900">{recipe.name}</p>
                    <p className="mt-1 font-mono text-label text-steel-400">
                      tags:{' '}
                      {recipe.dietaryTags.length > 0 ? recipe.dietaryTags.join(', ') : '(none)'}
                    </p>
                  </div>
                  {marks.length > 0 ? (
                    <DietMarks marks={marks} />
                  ) : (
                    <span className="font-mono text-label text-steel-400">no marks apply</span>
                  )}
                </div>
              </Ticket>
            )
          })}
        </div>
        <p className="text-label text-steel-400">
          Hover, Tab-focus, or click/tap any dot above to reveal its full name — the tooltip stays
          regardless of the new diet-* colors below, since color is still only a fast visual cue.
        </p>
      </PreviewSection>

      <PreviewSection title="Diet colors — all seven, plus a greyscale check">
        <div className="flex flex-col gap-4">
          <div>
            <p className="mb-2 text-label text-steel-400">Normal</p>
            <DietMarks marks={ALL_SEVEN_MARKS} />
          </div>
          <div style={{ filter: 'grayscale(100%)' }}>
            <p className="mb-2 text-label text-steel-400">Greyscale — vegan vs. meat check</p>
            <DietMarks marks={ALL_SEVEN_MARKS} />
          </div>
          <p className="text-label text-steel-400">
            vegan (#254020) and contains-meat (#B23A2E) were verified, not assumed: the original
            vegan value (#3F5B3E) rendered as the exact same grey as meat under Chrome's own
            grayscale(100%) filter (RGB 83,83,83 both) — hue-only separation with no lightness
            separation at all. This darker value renders at grey 56 against meat's grey 83, a real
            ~27-unit gap — see this task's own verbatim report for the full measurement.
          </p>
        </div>
      </PreviewSection>

      <PreviewSection title="Paper texture — paper-0 (grained) vs. paper-raised (ungrained), normal and magnified">
        <div className="grid grid-cols-2 gap-6">
          <div className="flex h-32 items-center justify-center rounded-sm border border-ink-900 bg-paper-0">
            <span className="text-label text-steel-400">paper-0, normal scale</span>
          </div>
          <div className="flex h-32 items-center justify-center rounded-sm border border-ink-900 bg-paper-raised">
            <span className="text-label text-steel-400">paper-raised, no grain</span>
          </div>
          <div
            className="col-span-2 h-32 rounded-sm border border-ink-900 bg-paper-0"
            style={{ backgroundSize: '480px 480px', imageRendering: 'pixelated' }}
          >
            <span className="ml-2 mt-2 inline-block text-label text-steel-400">
              paper-0, grain magnified ~5x (background-size forced up) — should read as fiber, not
              as a visible repeating tile
            </span>
          </div>
        </div>
      </PreviewSection>

      <PreviewSection title="Masthead — mirrors NavShell's own real markup">
        <div className="rounded-sm border border-ink-900 bg-paper-raised">
          <div className="flex items-baseline justify-between px-6 pt-4">
            <span className="text-title text-ink-900">MealSight</span>
            <span className="font-mono text-label text-ink-600">NO. 4F82A1C9</span>
          </div>
          <div className="border-b-2 border-ink-900" />
          <div className="flex items-center px-6 py-2">
            <span className="rounded-sm bg-signal-active/10 px-3 py-2 text-body-lg font-medium text-signal-active">
              Home
            </span>
          </div>
        </div>
        <p className="mt-2 text-label text-steel-400">
          The ticket number is real data, not decorative — a running recommendation's own session id
          while one is active, a stable placeholder ("NO. ————————") when idle.
        </p>
      </PreviewSection>

      <PreviewSection title="Empty-state illustrations — Pantry, Grocery List, History">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <EmptyState illustration="fridge" message="Your pantry is empty." />
          <EmptyState illustration="list-pad" message="Nothing on your grocery list yet." />
          <EmptyState illustration="spike" message="No meals logged yet." />
        </div>
      </PreviewSection>

      <PreviewSection title="Loading view — simulated with the real measured pacing">
        <LoadingDemo />
      </PreviewSection>

      <PreviewSection title="RecipeIcon, DietMarks, and Stamp side by side — confirming they read as distinct">
        <Ticket>
          <div className="flex items-start gap-4">
            <RecipeIcon category="hen" />
            <div className="flex flex-col gap-2">
              <p className="text-body-lg text-ink-900">Chicken Enchilada Casserole</p>
              <DietMarks marks={deriveDietaryMarks([], ['chicken breasts', 'cheese'])} />
              <div className="flex gap-2">
                <Stamp signal="positive">cookable</Stamp>
                <Stamp signal="info">partial nutrition data</Stamp>
              </div>
            </div>
          </div>
        </Ticket>
      </PreviewSection>

      <PreviewSection title="Stamp — all four signal states, upright">
        <div className="flex flex-wrap gap-4">
          <Stamp signal="active">in progress</Stamp>
          <Stamp signal="positive">cookable</Stamp>
          <Stamp signal="negative">not cookable</Stamp>
          <Stamp signal="info">partial nutrition data</Stamp>
        </div>
      </PreviewSection>

      <PreviewSection title="Interactive vs. static Ticket (hover, focus)">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <Ticket interactive onActivate={() => undefined}>
            <p className="text-body-lg text-ink-900">Interactive — hover and click me</p>
            <p className="mt-1 text-label text-steel-400">
              paper-hover fill on hover; focus outline on keyboard focus
            </p>
          </Ticket>
          <Ticket>
            <p className="text-body-lg text-ink-900">Static — no hover state at all</p>
            <p className="mt-1 text-label text-steel-400">Purely for display, never clickable</p>
          </Ticket>
        </div>
      </PreviewSection>

      <PreviewSection title="Focused Ticket — outline should now be visible on all four sides">
        <div style={{ width: 320 }}>
          <Ticket ref={focusedTicketRef} interactive onActivate={() => undefined}>
            <p className="text-body-lg text-ink-900">Focused on page load</p>
            <p className="mt-1 text-label text-steel-400">
              Tab-focused automatically so the outline is visible without interaction
            </p>
          </Ticket>
        </div>
      </PreviewSection>
    </div>
  )
}
