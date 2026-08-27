/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // The whole design system lives here, not in scattered class
      // strings — a page reaches for `bg-brand-600` or `text-body`,
      // never a raw hex or an arbitrary `text-[15px]`.
      colors: {
        brand: {
          50: '#f0fdf6',
          100: '#dcfce9',
          200: '#bbf7d3',
          300: '#86efb0',
          400: '#4ade85',
          500: '#22c562',
          600: '#16a34d',
          700: '#15803e',
          800: '#166534',
          900: '#14532b',
        },
        surface: {
          DEFAULT: '#ffffff',
          subtle: '#f8faf9',
          muted: '#f1f4f2',
        },
        ink: {
          DEFAULT: '#1c2420',
          muted: '#5b665f',
          faint: '#8a948d',
        },
        danger: {
          50: '#fef2f2',
          500: '#ef4444',
          600: '#dc2626',
        },
        warning: {
          50: '#fffbeb',
          500: '#f59e0b',
          600: '#d97706',
        },
      },
      spacing: {
        18: '4.5rem',
        22: '5.5rem',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
      },
      fontSize: {
        // A named type scale instead of ad hoc text-[13px] / text-[22px]
        // sprinkled through pages.
        caption: ['0.75rem', { lineHeight: '1rem' }],
        body: ['0.9375rem', { lineHeight: '1.5rem' }],
        subtitle: ['1.125rem', { lineHeight: '1.75rem', fontWeight: '600' }],
        title: ['1.5rem', { lineHeight: '2rem', fontWeight: '700' }],
        display: ['2rem', { lineHeight: '2.5rem', fontWeight: '800' }],
      },
      borderRadius: {
        card: '0.75rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(0 0 0 / 0.05), 0 1px 3px 0 rgb(0 0 0 / 0.06)',
      },
    },
  },
  plugins: [],
}
