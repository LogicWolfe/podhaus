// Forest-green theme for the podhaus docs site. Loaded after tailwind.js
// (the Play CDN bundle) — Tailwind reads window.tailwind.config and uses
// it for JIT class generation on every DOM scan. Single source of truth
// for the theme: editing this file changes every page on next reload.

tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Inter"', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', '"Liberation Mono"', 'monospace'],
      },
      colors: {
        // Forest-green ramp, anchored at #14532d (Tailwind green-900).
        // Used for links, current-nav highlight, accents.
        primary: {
          50:  '#f1f8f2',
          100: '#dcefdf',
          200: '#bbdfc2',
          300: '#8cc596',
          400: '#5ba668',
          500: '#3a8847',
          600: '#2a6c37',
          700: '#23562e',
          800: '#1d4527',
          900: '#14532d',
          950: '#082015',
          DEFAULT: '#23562e',
        },
        // Surface colors driven by CSS custom properties (see style.css)
        // so light/dark switching is a single root-level class flip with
        // no Tailwind reflow needed.
        bg:           'rgb(var(--bg) / <alpha-value>)',
        'bg-soft':    'rgb(var(--bg-soft) / <alpha-value>)',
        'bg-code':    'rgb(var(--bg-code) / <alpha-value>)',
        text:         'rgb(var(--text) / <alpha-value>)',
        'text-muted': 'rgb(var(--text-muted) / <alpha-value>)',
        border:       'rgb(var(--border) / <alpha-value>)',
      },
      maxWidth: {
        prose: '46rem',
      },
      typography: ({ theme }) => ({
        DEFAULT: {
          css: {
            '--tw-prose-body':         'rgb(var(--text))',
            '--tw-prose-headings':     'rgb(var(--text))',
            '--tw-prose-lead':         'rgb(var(--text))',
            '--tw-prose-links':        theme('colors.primary.700'),
            '--tw-prose-bold':         'rgb(var(--text))',
            '--tw-prose-counters':     'rgb(var(--text-muted))',
            '--tw-prose-bullets':      'rgb(var(--text-muted))',
            '--tw-prose-hr':           'rgb(var(--border))',
            '--tw-prose-quotes':       'rgb(var(--text))',
            '--tw-prose-quote-borders': theme('colors.primary.500'),
            '--tw-prose-captions':     'rgb(var(--text-muted))',
            '--tw-prose-code':         'rgb(var(--text))',
            '--tw-prose-pre-code':     '#e6edea',
            '--tw-prose-pre-bg':       '#0f1d17',
            '--tw-prose-th-borders':   'rgb(var(--border))',
            '--tw-prose-td-borders':   'rgb(var(--border))',
            '--tw-prose-invert-body':       'rgb(var(--text))',
            '--tw-prose-invert-headings':   'rgb(var(--text))',
            '--tw-prose-invert-links':      theme('colors.primary.300'),
            '--tw-prose-invert-bold':       'rgb(var(--text))',
            '--tw-prose-invert-counters':   'rgb(var(--text-muted))',
            '--tw-prose-invert-bullets':    'rgb(var(--text-muted))',
            '--tw-prose-invert-hr':         'rgb(var(--border))',
            '--tw-prose-invert-quotes':     'rgb(var(--text))',
            '--tw-prose-invert-quote-borders': theme('colors.primary.500'),
            '--tw-prose-invert-captions':   'rgb(var(--text-muted))',
            '--tw-prose-invert-code':       'rgb(var(--text))',
            '--tw-prose-invert-pre-code':   '#e6edea',
            '--tw-prose-invert-pre-bg':     '#0a1410',
            '--tw-prose-invert-th-borders': 'rgb(var(--border))',
            '--tw-prose-invert-td-borders': 'rgb(var(--border))',
            code: {
              fontWeight: '500',
              backgroundColor: 'rgb(var(--bg-code))',
              padding: '0.15em 0.4em',
              borderRadius: '0.3rem',
            },
            'code::before': { content: 'none' },
            'code::after':  { content: 'none' },
            'pre code': {
              backgroundColor: 'transparent',
              padding: '0',
            },
            a: {
              textDecoration: 'none',
              fontWeight: '500',
              '&:hover': { textDecoration: 'underline' },
            },
            'h2, h3, h4': {
              scrollMarginTop: '5rem',
            },
            table: {
              fontSize: '0.9em',
            },
          },
        },
      }),
    },
  },
};
