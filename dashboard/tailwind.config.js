/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#05080E",
        surface: {
          DEFAULT: "#0A0F18",
          raised: "#101722",
          hover: "#151D2B",
          border: "rgba(148,163,184,0.12)",
        },
        brand: {
          DEFAULT: "#3D7EFF",
          muted: "#2563EB",
          glow: "rgba(61,126,255,0.15)",
        },
        profit: {
          DEFAULT: "#34D399",
          muted: "#10B981",
        },
        loss: {
          DEFAULT: "#F87171",
          muted: "#EF4444",
        },
        warn: {
          DEFAULT: "#FBBF24",
          muted: "#F59E0B",
        },
        // legacy aliases
        accent: {
          DEFAULT: "#3D7EFF",
          muted: "#2563EB",
        },
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 32px rgba(0,0,0,0.35)",
        glow: "0 0 24px rgba(61,126,255,0.12)",
      },
      backgroundImage: {
        "terminal-grid":
          "linear-gradient(rgba(148,163,184,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.03) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "48px 48px",
      },
      animation: {
        "pulse-soft": "pulse-soft 2.5s ease-in-out infinite",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
    },
  },
  plugins: [],
};
