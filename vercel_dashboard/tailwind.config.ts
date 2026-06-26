import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Green Energy Park palette.
        // brand-600 ≈ #76B82A (gepgreen), brand-800 ≈ #3A6E24 (gepdark).
        brand: {
          50: "#f4f9ec",
          100: "#e6f2d4",
          200: "#cde6aa",
          300: "#aed576",
          400: "#92c84d",
          500: "#82c038",
          600: "#76b82a", // GEP primary green
          700: "#5e9523",
          800: "#3a6e24", // GEP dark green
          900: "#2f561d",
        },
        gep: {
          green: "#76b82a",
          dark: "#3a6e24",
          gray: "#58595b",
          tint: "#f6faf0",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06)",
        "card-hover":
          "0 4px 12px rgba(16, 24, 40, 0.08), 0 2px 4px rgba(16, 24, 40, 0.04)",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.85)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.6s ease-in-out infinite",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
