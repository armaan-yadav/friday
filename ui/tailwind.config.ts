import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Outfit', 'sans-serif'],
        mono: ['"Space Mono"', 'monospace'],
      },
      colors: {
        bg:      '#080810',
        surface: '#0e0e1a',
        card:    '#131320',
        green:   '#00f5a0',
        purple:  '#9b7fff',
        red:     '#ff4f6e',
        amber:   '#ffc94a',
        text1:   '#e2e2f0',
        text2:   '#8888aa',
        text3:   '#44445a',
      },
      keyframes: {
        pulse2:    { '0%,100%': { opacity: '1', transform: 'scale(1)' }, '50%': { opacity: '0.5', transform: 'scale(0.75)' } },
        blink:     { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.15' } },
        slidein:   { to: { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: {
        pulse2:    'pulse2 2s ease-in-out infinite',
        blink:     'blink 0.5s linear infinite',
        blinkSlow: 'blink 0.8s linear infinite',
        slidein:   'slidein 0.4s cubic-bezier(0.25,0.8,0.25,1) forwards',
      },
    },
  },
  plugins: [],
} satisfies Config
