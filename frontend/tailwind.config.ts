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
        // A hairline that is actually visible. slate-200 at 60-80% opacity --
        // which this UI used for every card edge and divider -- disappears
        // against white on a bright screen, so panels floated with nothing
        // separating them. `line` is a card's own edge, `line-soft` a divider
        // inside one, `line-strong` a hover or focus edge.
        line: {
          DEFAULT: "#d3dbe6",
          soft: "#e4e9f0",
          strong: "#b8c3d2",
        },
      },
      // Persian sits lower and denser than Latin at the same nominal size, and
      // this UI is read at a glance while scanning a feed. The whole scale is
      // therefore a notch larger than Tailwind's default, with line heights
      // opened up: 13.5px is the smallest type in the product, and nothing
      // smaller than that is legitimate.
      fontSize: {
        xs: ["0.8438rem", { lineHeight: "1.4rem" }],
        sm: ["0.9375rem", { lineHeight: "1.65rem" }],
        base: ["1.0625rem", { lineHeight: "1.85rem" }],
        lg: ["1.1875rem", { lineHeight: "2rem" }],
        xl: ["1.375rem", { lineHeight: "2.15rem" }],
        "2xl": ["1.625rem", { lineHeight: "2.4rem" }],
        "3xl": ["2rem", { lineHeight: "2.75rem" }],
      },
      fontFamily: {
        // The emoji faces are not decoration: Persian adverts are written with
        // ✅ and ☎ as bullet characters, and Vazirmatn carries none of them, so
        // without a fallback every one rendered as a tofu box mid-sentence.
        sans: [
          "var(--font-vazirmatn)",
          "Tahoma",
          "Segoe UI Emoji",
          "Noto Color Emoji",
          "Apple Color Emoji",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
export default config;
