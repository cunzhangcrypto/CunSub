/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#0a0e1a',
          card: '#131826',
          hover: '#1a2035',
          border: '#1e293b',
        },
        accent: {
          cyan: '#00d4ff',
          purple: '#7c3aed',
          green: '#10b981',
          amber: '#f59e0b',
          red: '#ef4444',
        },
        tx: {
          primary: '#ffffff',
          secondary: '#ffffff',
          dim: '#ffffff',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Consolas', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'glow': 'glow 2s ease-in-out infinite',
        'flow': 'flow 3s linear infinite',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        glow: {
          '0%, 100%': { boxShadow: '0 0 8px rgba(0, 212, 255, 0.3)' },
          '50%': { boxShadow: '0 0 24px rgba(0, 212, 255, 0.6)' },
        },
        flow: {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '200% 50%' },
        },
      }
    }
  },
  plugins: []
}
