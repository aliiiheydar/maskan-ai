import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        // Tier 1 = strong matches (Utility >= 0.70): gold/green per docs/FRONTEND_STATE.md SS3.
        tier1: {
          DEFAULT: "#15803d",
          gold: "#b45309",
          light: "#dcfce7",
        },
        // Tier 2 = secondary/trade-off matches (0.45 <= Utility < 0.70): blue/gray.
        tier2: {
          DEFAULT: "#2563eb",
          gray: "#64748b",
          light: "#eff6ff",
        },
      },
      fontFamily: {
        sans: ["var(--font-vazirmatn)", "Tahoma", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
