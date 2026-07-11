import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        steel: {
          950: "#0d0f11",
          900: "#131619",
          850: "#181c20",
          800: "#1e2328",
          700: "#2a3036",
          600: "#3a424a",
          500: "#556069",
          400: "#7b8791",
          300: "#a7b1ba",
        },
        hazard: {
          500: "#f5a300",
          400: "#ffb61a",
          600: "#d98c00",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Impact", "sans-serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      backgroundImage: {
        "hazard-stripes":
          "repeating-linear-gradient(45deg, #f5a300 0, #f5a300 12px, #131619 12px, #131619 24px)",
        "grid-steel":
          "linear-gradient(to right, rgba(85,96,105,0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(85,96,105,0.08) 1px, transparent 1px)",
      },
    },
  },
  plugins: [],
};

export default config;
