/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** Vitest, for the logic that is not React.
 *
 * What is worth testing here is the part of the frontend that decides things:
 * the store's search-request assembly and its capability gating, and the pure
 * formatting and colour helpers the whole UI reads numbers through. Rendering
 * is left to the live pass -- these run in node, with no DOM to set up.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors tsconfig's `@/*` alias; vitest does not read tsconfig paths.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
