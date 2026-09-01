"use client";

import { useEffect, useState } from "react";

/** Tailwind's `lg`: the width at which the panel, the feed and the map stop
 * being tabs and become three columns side by side (see app/page.tsx).
 *
 * Several behaviours differ either side of it -- which surface a selection
 * brings forward, whether the map has to carry its own "open this one"
 * affordance -- and they all have to agree with the layout, so they read the
 * one query rather than each guessing at a width. */
export const DESKTOP_QUERY = "(min-width: 1024px)";

/** For event handlers and effects, where the answer is only needed once. */
export const isDesktop = (): boolean =>
  typeof window !== "undefined" && window.matchMedia(DESKTOP_QUERY).matches;

/** For rendering. Starts false so the server and the first client paint agree,
 * then settles on the real answer before paint. */
export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY);
    const sync = () => setDesktop(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return desktop;
}
