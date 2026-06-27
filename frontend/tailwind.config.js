/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#EEF2FF',
          100: '#E0E7FF',
          200: '#C7D2FE',
          300: '#A5B4FC',
          400: '#818CF8',
          500: '#6366F1', // Indigo 500
          600: '#4F46E5', // Indigo 600
          700: '#4338CA', // Indigo 700
          800: '#3730A3',
          900: '#312E81',
          950: '#1E1B4B',
        },
        slate: {
          900: '#0F172A', // Background dark
          800: '#1E293B', // Card background
          700: '#334155', // Border color
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'glass-sm': '0 2px 8px 0 rgba(0, 0, 0, 0.2)',
        'glass': '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
        'glass-accent': '0 8px 32px 0 rgba(99, 102, 241, 0.12)',
        'glow': '0 0 15px 2px rgba(99, 102, 241, 0.25)',
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
}
