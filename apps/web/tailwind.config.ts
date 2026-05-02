import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // VS Code Dark+ palette — used by the slice-6 IDE only.
        ide: {
          bg: '#1e1e1e',
          panel: '#252526',
          deep: '#181818',
          tab: '#2d2d2d',
          tabActive: '#1e1e1e',
          border: '#3c3c3c',
          borderSoft: '#2d2d2d',
          hover: '#2a2d2e',
          active: '#37373d',
          text: '#cccccc',
          textMuted: '#9a9a9a',
          textDim: '#6b6b6b',
          textBright: '#ffffff',
          accent: '#007acc',
          accentHover: '#0e639c',
          danger: '#f48771',
          warn: '#dcdcaa',
          ok: '#4ec9b0',
        },
      },
    },
  },
  plugins: [],
};

export default config;
