/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0f1419",
          raised: "#1a2332",
          border: "#2a3544",
        },
        accent: {
          DEFAULT: "#3b82f6",
          muted: "#1d4ed8",
        },
        forecast: "#ef4444",
        history: "#60a5fa",
        // Semantic P/L colors — each clears 4.5:1 contrast on surface-raised (#1a2332).
        gain: "#4ade80",
        loss: "#f87171",
        muted: "#94a3b8",
      },
      fontSize: {
        "data-xs": ["11px", { lineHeight: "14px" }],
        "data-sm": ["12px", { lineHeight: "16px" }],
        "data-md": ["13px", { lineHeight: "18px" }],
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
