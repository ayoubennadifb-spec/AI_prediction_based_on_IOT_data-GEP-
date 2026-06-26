import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f4f9ec",
          100: "#e6f2d4",
          200: "#cde6aa",
          300: "#aed576",
          400: "#92c84d",
          500: "#82c038",
          600: "#76b82a",
          700: "#5e9523",
          800: "#3a6e24",
          900: "#2f561d",
        },
        gep: {
          green: "#76b82a",
          dark: "#3a6e24",
          gray: "#58595b",
          tint: "#f8faf6",
        },
      },
      boxShadow: {
        card: "0 1px 3px rgba(16,24,40,0.06), 0 1px 2px rgba(16,24,40,0.04)",
        "card-hover": "0 8px 24px rgba(16,24,40,0.10), 0 2px 6px rgba(16,24,40,0.06)",
        glow: "0 0 0 3px rgba(118,184,42,0.15)",
        "glow-sm": "0 0 0 2px rgba(118,184,42,0.12)",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.85)" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.6s ease-in-out infinite",
        shimmer: "shimmer 1.5s infinite",
        "fade-in": "fade-in 0.3s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
