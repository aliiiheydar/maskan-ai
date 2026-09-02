import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

/** Vazirmatn, the typeface Persian marketplaces (Divar included) read like.
 *
 * Self-hosted from the installed @fontsource-variable package rather than
 * fetched by next/font/google: that fetch happens at build time and fails
 * silently, leaving the whole Persian UI in Tahoma. One variable file covers
 * 100..900, so every weight the design uses costs nothing extra.
 *
 * The files are produced by scripts/copy-map-assets.mjs on pre(dev|build). */
const vazirmatn = localFont({
  src: [
    { path: "./fonts/vazirmatn-arabic-wght-normal.woff2", weight: "100 900", style: "normal" },
    { path: "./fonts/vazirmatn-latin-wght-normal.woff2", weight: "100 900", style: "normal" },
  ],
  variable: "--font-vazirmatn",
  display: "swap",
  // Tahoma is the Persian fallback every Windows and most Linux desktops
  // have; the Latin list keeps mixed-script runs from jumping.
  fallback: ["Tahoma", "Segoe UI", "system-ui", "sans-serif"],
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  // The ranking is the product, so the tab says so. It used to read «جستجوی
  // هوشمند», which is now the name of one mode -- and the least important
  // claim the app can make about itself.
  title: "مسکن‌یار | جستجو و رتبه‌بندی اجاره در تهران",
  description:
    "اجارهٔ تهران، مرتب‌شده بر اساس میزان تطابق با خواستهٔ شما: رتبه‌بندی چندمعیاره با احتساب تبدیل، دسترسی به مترو و کیفیت محله.",
};

export default function RootLayout({
  children,
  modal,
}: Readonly<{
  children: React.ReactNode;
  // Parallel slot for the intercepted /listing/[id] route: a property opens as
  // an overlay above whatever search the user had built, rather than replacing
  // it. Renders null (see @modal/default.tsx) on every other route.
  modal: React.ReactNode;
}>) {
  return (
    <html lang="fa" dir="rtl">
      <body className={`${vazirmatn.variable} font-sans antialiased`}>
        {children}
        {modal}
      </body>
    </html>
  );
}
