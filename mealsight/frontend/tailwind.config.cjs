/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // "The Ticket Rail" design system — every value here is a fixed
      // spec token, not a placeholder. A page reaches for `bg-paper-0`
      // or `text-signal-negative`, never a raw hex or an arbitrary
      // value. The four signal-* colors are semantic, not feature-
      // specific: every status in every current and future feature
      // maps to one of exactly these four. A new status color is a
      // design-system change to flag, never a per-feature decision.
      colors: {
        paper: {
          0: '#EAEBE3', // base app background
          1: '#DFE0D6', // recessed surfaces (Wells)
          raised: '#F5F5F0', // Tickets, panels — anything above the base
          hover: '#EFEFE8', // hover fill for clickable Tickets
        },
        ink: {
          900: '#1C1D18', // primary text, borders, icons
          600: '#4A4C42', // secondary text
        },
        steel: {
          400: '#8B8D82', // tertiary text, disabled states, dividers
        },
        signal: {
          active: '#C7862B', // universal "in progress" — any feature, any page
          positive: '#3F5B3E', // universal "succeeded / confirmed"
          negative: '#B23A2E', // universal "blocked / failed / can't do this"
          info: '#3A5A6B', // universal neutral-informational
        },
        // diet-* is a DELIBERATE second semantic group, not signal-*
        // stretched further. signal-* means SYSTEM STATE — in
        // progress, succeeded, blocked, informational — a vocabulary
        // about what the APP is doing. diet-* means a PROPERTY OF THE
        // FOOD — a vocabulary about what the RECIPE is. They are
        // different categories of fact, so they get different color
        // pools rather than one stretched palette where "signal-info"
        // has to mean three unrelated things at once (dairy-free,
        // gluten-free, AND nut-free, indistinguishable by color alone
        // — exactly the bug this group exists to fix). Every future
        // SYSTEM state still maps to one of the four signal-* colors;
        // every future DIETARY property extends diet-*, never signal-*.
        diet: {
          // Darker than the original #3F5B3E: measured in Chrome's own
          // grayscale(100%) filter, #3F5B3E and meat's #B23A2E rendered
          // as literally the same grey (RGB 83,83,83) — hue-only
          // separation, no lightness separation at all, the opposite of
          // this group's own stated intent. This value renders at grey
          // 56 against meat's 83, a real ~27-unit gap.
          vegan: '#254020',
          vegetarian: '#6B8E4E',
          meat: '#B23A2E',
          fish: '#3A7D8C',
          dairyfree: '#8A6BA1',
          glutenfree: '#C08A3E',
          nutfree: '#7A5C3E',
        },
      },
      fontFamily: {
        // Self-hosted, subsetted to Latin + numerals (see src/assets/
        // fonts and src/fonts.css) — no Google Fonts CDN request.
        sans: ['Public Sans', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // spacing stays an EXTEND, not a replacement, unlike fontSize/
      // borderRadius/boxShadow below — deliberately, and only for this
      // one token group. The spec's own 4-point scale (4/8/12/16/24/
      // 32/48/64) already sits at Tailwind's own default keys 1/2/3/4/
      // 6/8/12/16 with the identical pixel values, so nothing needed
      // adding for THOSE eight. But a full replacement (removing every
      // other default key: 5, 7, 1.5, 2.5, 9, 20, 32, 44, ...) would
      // silently stop generating roughly twenty utility classes
      // already in use across the nine existing components this
      // session must NOT redesign (h-2.5/w-9/w-20/w-32/h-5/py-1.5/
      // gap-1.5/gap-0.5/px-5, etc. — verified by grep before making
      // this call, not assumed). Restricting the SPACING scale to
      // exactly eight values is a real, correct, load-bearing part of
      // this design system — it is deferred here specifically to avoid
      // an invisible layout regression across every untouched
      // component, and must be enforced for real once those
      // components are actually restyled under this system.
      spacing: {
        0: '0px',
        1: '4px',
        2: '8px',
        3: '12px',
        4: '16px',
        6: '24px',
        8: '32px',
        12: '48px',
        16: '64px',
      },
      // The one motion this system permits outside a Strip's own live
      // timer: RecipeIcon's animated variant, a gentle idle bob used
      // ONLY while a recommendation is actually being computed (not
      // wired into the real loading UI yet — see RecipeIcon's own
      // comment). Never applied to a settled, rendered result — this
      // design system's one motion rule is "animate only when
      // something is genuinely, currently happening."
      keyframes: {
        'icon-idle': {
          '0%, 100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%': { transform: 'translateY(-3px) rotate(-3deg)' },
        },
        // A Strip's own one-time entrance — "printing in," the literal
        // ticket-rail metaphor, not a generic fade/slide. Only ever
        // plays once, on mount, for a message that just genuinely
        // arrived; a settled, already-rendered Strip never replays it.
        'strip-print-in': {
          '0%': { transform: 'translateY(-6px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        'icon-idle': 'icon-idle 2.4s ease-in-out infinite',
        'strip-print-in': 'strip-print-in 180ms ease-out',
      },
    },
    // theme.fontSize, theme.borderRadius, and theme.boxShadow ARE
    // replaced wholesale (not merged via `extend`) — each is a closed,
    // exhaustive set the spec states as "no values outside it, ever,"
    // and — unlike spacing above — grepping the whole app first
    // confirmed nothing currently in use depends on any value these
    // replacements remove (no text-xs/sm/base/lg/..., no rounded-md/
    // lg/xl/..., no shadow-sm/md/lg/... anywhere), so none of these
    // three carries the same regression risk spacing does.
    fontSize: {
      // The five-step scale, one name per use-case named in the spec.
      // Weight is NOT baked in for label/body/body-lg — Public Sans'
      // own 400/500/600 weights are applied independently via
      // font-normal/font-medium/font-semibold, orthogonal to size.
      // heading/title bake in 600 (semibold) as their default weight
      // since a section or page header is never body-weight text, and
      // 600 is the heaviest weight this system allows (Public Sans
      // ships no 700/800 — there is no bolder option to reach for).
      label: ['0.75rem', { lineHeight: '1rem' }], // 12px — labels + timestamps
      body: ['0.875rem', { lineHeight: '1.25rem' }], // 14px — body
      'body-lg': ['1rem', { lineHeight: '1.5rem' }], // 16px — primary body
      heading: ['1.25rem', { lineHeight: '1.75rem', fontWeight: '600' }], // 20px — section headers
      title: ['1.75rem', { lineHeight: '2.25rem', fontWeight: '600' }], // 28px — page title, once per page
    },
    borderRadius: {
      // Exactly two radii, full stop — no sm/md/lg/xl/2xl/3xl ladder.
      none: '0px',
      sm: '2px', // Tickets/cards — bottom two corners only, applied per-element
      pill: '9999px', // Stamps only
      full: '9999px', // Tailwind's own circular utilities (rounded-full) keep working
    },
    boxShadow: {
      // No OUTER elevation anywhere in this system — Tailwind's own
      // default outer-shadow scale (shadow-sm/md/lg/...) is
      // deliberately left unreachable by not re-declaring it here, for
      // the same "structurally impossible, not just discouraged" reason
      // as spacing above. `well` is the one exception: an INSET shadow
      // only, used exclusively by the Well primitive (recessed input
      // containers) — it reads as a surface pressed IN, never a card
      // lifted up, so it doesn't reintroduce elevation through the back
      // door.
      none: 'none',
      well: 'inset 0 1px 3px 0 rgba(28, 29, 24, 0.18)',
    },
  },
  plugins: [],
}
