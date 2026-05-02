/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 900: "#0f172a", 700: "#334155", 500: "#64748b" },
      },
    },
  },
  plugins: [],
};
