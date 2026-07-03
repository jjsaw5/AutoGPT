/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        risk: "#b91c1c",
        caution: "#b45309",
        good: "#047857",
      },
    },
  },
  plugins: [],
};
