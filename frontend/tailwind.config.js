/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        tb: {
          bg:        '#1a1a1a',
          panel:     '#232323',
          header:    '#2d2d2d',
          border:    '#3a3a3a',
          accent:    '#a259ff',
          'accent-dim': '#7b3fc7',
          text:      '#e0e0e0',
          muted:     '#9a9a9a',
          'wave-orig': '#4a9eff',
          'wave-dub':  '#a259ff',
          'wave-bg':   '#3d7a3d',
          emotion:   '#ff6b35',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
