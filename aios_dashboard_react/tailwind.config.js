/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Black Terminal — single source remains tokens.css CSS vars,
        // Tailwind maps to them so no parallel palette.
        black: "#000000",
        panel: "#0C0C0C",
        edge: "#232323",
        lime: "#D4FF3F",
        red: "#FF5C5C",
        amber: "#FFC83C",
        gray: { DEFAULT: "#9E9E9E", dim: "#5A5A5A" },
        // status tokens (same as --status-* in tokens.css)
        status: {
          available: "#D4FF3F",
          "no-data": "#FF5C5C",
          insufficient: "#FFC83C",
          "not-verifiable": "#9E9E9E",
        },
      },
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        body: ["IBM Plex Sans", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "Consolas", "monospace"],
      },
      spacing: {
        // mirrors --sp-* scale
        "sp-1": "4px",
        "sp-2": "8px",
        "sp-3": "12px",
        "sp-4": "16px",
        "sp-5": "24px",
        "sp-6": "32px",
      },
    },
  },
  plugins: [],
}
