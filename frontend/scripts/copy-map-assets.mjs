/**
 * Copies the browser assets that MapLibre has to load by URL at runtime
 * (rather than through the bundler) out of node_modules and into
 * public/vendor/maplibre/.
 *
 * Two of them can't go through webpack:
 *
 * - maplibre-gl-worker.mjs (+ the shared chunk it imports): MapLibre normally
 *   locates its own worker relative to `import.meta.url`, which webpack
 *   rewrites, so the worker it builds never resolves its code. It then hangs
 *   with no error and every tile sits in "loading" forever. Pointing
 *   setWorkerUrl() at a real self-hosted file avoids the guesswork.
 * - mapbox-gl-rtl-text.js: loaded into the worker by URL, and required for
 *   Persian labels to be shaped and ordered correctly.
 *
 * Copying at pre(dev|build) time -- rather than checking vendored copies into
 * git -- keeps these byte-identical to the installed maplibre-gl version, so a
 * dependency bump can't leave a stale worker behind.
 */

import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "public", "vendor", "maplibre");

const ASSETS = [
  "maplibre-gl/dist/maplibre-gl-worker.mjs",
  "maplibre-gl/dist/maplibre-gl-shared.mjs",
  "@mapbox/mapbox-gl-rtl-text/dist/mapbox-gl-rtl-text.js",
];

await mkdir(outDir, { recursive: true });
for (const asset of ASSETS) {
  const name = asset.slice(asset.lastIndexOf("/") + 1);
  await copyFile(join(root, "node_modules", asset), join(outDir, name));
}

/* Vazirmatn, self-hosted.
 *
 * The app used to pull it through next/font/google, which fetches the file at
 * build time -- and when that fetch fails (an offline build, a blocked CDN, a
 * corporate proxy) Next does not fail the build: it silently keeps only the
 * metric-adjusted fallback, and the entire Persian UI renders in Tahoma. That
 * is exactly what was happening here. Copying the woff2 out of the installed
 * package makes the typeface a build artifact like any other, so it either
 * works or the build breaks loudly. */
const fontOutDir = join(root, "src", "app", "fonts");
const FONTS = [
  "@fontsource-variable/vazirmatn/files/vazirmatn-arabic-wght-normal.woff2",
  "@fontsource-variable/vazirmatn/files/vazirmatn-latin-wght-normal.woff2",
];

await mkdir(fontOutDir, { recursive: true });
for (const font of FONTS) {
  const name = font.slice(font.lastIndexOf("/") + 1);
  await copyFile(join(root, "node_modules", font), join(fontOutDir, name));
}
