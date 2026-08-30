/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        lms: {
          navy: {
            950: "#090E1A",
            900: "#0F172A",
            800: "#1E293B",
            700: "#334155",
          },
          blue: {
            50: "#EFF6FF",
            100: "#DBEAFE",
            500: "#3B82F6",
            600: "#2563EB",
            700: "#1D4ED8",
          },
          canvas: "#F8FAFC",
          panel: "#FFFFFF",
          border: "#E2E8F0",
          status: {
            green: "#10B981",
            greenBg: "#ECFDF5",
            amber: "#F59E0B",
            amberBg: "#FFFBEB",
            red: "#EF4444",
            redBg: "#FEF2F2",
          },
          text: {
            primary: "#0F172A",
            secondary: "#475569",
            muted: "#94A3B8",
            light: "#F8FAFC",
            dim: "#94A3B8",
          }
        }
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          'Oxygen',
          'Ubuntu',
          'Cantarell',
          '"Open Sans"',
          '"Helvetica Neue"',
          'sans-serif'
        ],
      }
    },
  },
  plugins: [],
}
