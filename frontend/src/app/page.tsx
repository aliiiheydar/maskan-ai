"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { List, Loader2, Map as MapIcon, MessageSquare, SlidersHorizontal } from "lucide-react";
import clsx from "clsx";

import Header from "@/components/Header";
import ChatPanel from "@/components/Chat/ChatPanel";
import ClassicFilterPanel from "@/components/Filters/ClassicFilterPanel";
import ListingFeed from "@/components/Listings/ListingFeed";
import { DESKTOP_QUERY, isDesktop } from "@/lib/breakpoints";
import { useSearchStore } from "@/store/useSearchStore";

// Leaflet touches `window` at import time, so it can never run during SSR.
const NeshanMap = dynamic(() => import("@/components/Map/NeshanMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
      <Loader2 className="animate-spin" size={16} />
      در حال بارگذاری نقشه...
    </div>
  ),
});

/** Which of the three surfaces a phone is looking at.
 *
 * On a desktop the panel, the feed and the map are three columns side by side.
 * A phone has room for exactly one, and stacking them -- which is what this
 * layout did -- produced a screen where half a feed sat above a map, neither
 * was usable, and nothing said the other two existed. They become tabs
 * instead, which is how every map-plus-list product on a phone works. */
type MobileView = "panel" | "feed" | "map";

/** How long the map stays up after a pin has been dropped on it.
 *
 * Picking a workplace or a neighborhood on a phone means leaving the filter
 * panel for the map and coming back. Coming back the instant the tap lands
 * would flip the screen away before the user has seen where their pin went,
 * so the marker gets a beat on screen first. */
const RETURN_FROM_PICK_MS = 500;

export default function Home() {
  const mode = useSearchStore((state) => state.mode);
  const setMode = useSearchStore((state) => state.setMode);
  const runSearch = useSearchStore((state) => state.runSearch);
  const loadAppConfig = useSearchStore((state) => state.loadAppConfig);
  const isPicking = useSearchStore(
    (state) => state.isPickingWorkplace || state.isPickingNeighborhood,
  );
  const [mobileView, setMobileView] = useState<MobileView>("feed");

  /** Moves the phone's tab, and only the phone's.
   *
   * The tab state paints below `lg` only, but the effects that drive it fire
   * on every screen, so they ask first: a desktop user who selects a listing
   * must not have this moved silently under them and then find the map
   * showing the moment they narrow the window. */
  const showOnPhone = useCallback((view: MobileView) => {
    if (isDesktop()) return;
    setMobileView(view);
  }, []);

  useEffect(() => {
    runSearch();
    // Which optional features this backend actually has, asked once. The mode
    // switch renders off it, so it is fetched here rather than by the header:
    // the answer outlives any one component.
    void loadAppConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Map-explore is a desktop surface: it is a mode whose whole point is
  // reading the map and the feed against each other, and on a phone those are
  // two tabs, so it degrades to a map with a filter panel that does nothing.
  // It is not offered below `lg` (see Header), and a window narrowed into
  // that range hands the user back the filters rather than a dead mode.
  useEffect(() => {
    if (mode !== "map") return;
    const narrow = window.matchMedia(`not all and ${DESKTOP_QUERY}`);
    const enforce = () => {
      if (narrow.matches) setMode("classic");
    };
    enforce();
    narrow.addEventListener("change", enforce);
    return () => narrow.removeEventListener("change", enforce);
  }, [mode, setMode]);

  /* Selecting a property deliberately does *not* move a phone to the map.
     Picking a card is how someone reads down a list -- comparing one against
     the next -- and throwing them onto the map each time took the list away
     mid-comparison and made getting back a two-tap round trip. The map still
     flies to the selection; it just does it on the tab where the map is, and
     «نقشه» is one tap away for the user who wants to see where it is. */

  /** Picking a point on the map, from a panel that is not on screen with it. */
  const wasPicking = useRef(false);
  useEffect(() => {
    if (isPicking) {
      wasPicking.current = true;
      showOnPhone("map");
      return;
    }
    if (!wasPicking.current) return;
    wasPicking.current = false;
    const timer = setTimeout(() => showOnPhone("panel"), RETURN_FROM_PICK_MS);
    return () => clearTimeout(timer);
  }, [isPicking, showOnPhone]);

  const tabs: { value: MobileView; label: string; Icon: typeof List }[] = [
    {
      value: "panel",
      label: mode === "intelligent" ? "گفتگو" : "فیلترها",
      Icon: mode === "intelligent" ? MessageSquare : SlidersHorizontal,
    },
    { value: "feed", label: "فهرست", Icon: List },
    { value: "map", label: "نقشه", Icon: MapIcon },
  ];

  return (
    // `dvh` where it exists: on a phone `100vh` is the height the window would
    // have with the browser's own bars retracted, so the layout was always
    // taller than the screen actually showing it -- the floating view switcher
    // sat under the address bar until the user scrolled.
    <div className="flex h-screen flex-col bg-slate-50 supports-[height:100dvh]:h-[100dvh]">
      <Header />
      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* Map-explore has no third panel. Its filters do not apply, so the
            column had nothing in it but a paragraph saying so -- 360px of
            empty white next to the one surface the mode is actually about.
            The explanation moved into the feed, which is where the user finds
            out what this mode returns anyway. */}
        {mode !== "map" && (
          // Adaptive rather than a hard 360px: this is the product's lead
          // surface, and on a wide screen the extra room is the difference
          // between a range row that fits and one that wraps. It grows with
          // the window and stops before it starts eating the map.
          <section
            className={clsx(
              "min-h-0 bg-white lg:flex lg:w-[clamp(23rem,26vw,27rem)] lg:shrink-0 lg:border-s lg:border-line",
              mobileView === "panel" ? "flex flex-1" : "hidden",
            )}
          >
            {mode === "intelligent" && <ChatPanel />}
            {mode === "classic" && <ClassicFilterPanel />}
          </section>
        )}

        {/* The feed is a column of summaries; the map is where the searching
            actually happens, so it gets the room. Adaptive between the two,
            like the panel beside it: a hard 440px was wider than the cards
            need on a laptop and narrower than they deserve on a 27-inch
            screen, and it is the card -- photo, price panel, fact row -- that
            decides how much room is enough. */}
        <section
          className={clsx(
            "min-h-0 border-s border-line bg-white lg:flex lg:w-[clamp(24rem,27vw,28rem)] lg:flex-none",
            mobileView === "feed" ? "flex flex-1" : "hidden",
          )}
        >
          <ListingFeed />
        </section>

        <section className={clsx("min-h-0 lg:flex lg:flex-1", mobileView === "map" ? "flex flex-1" : "hidden")}>
          <NeshanMap />
        </section>
      </main>

      {/* The phone's way between the three. Floating over the surface rather
          than taking a strip of its own: on a 844px-tall screen every row of
          permanent chrome is a listing the user cannot see. */}
      <nav className="pointer-events-none fixed inset-x-0 bottom-0 z-[400] flex justify-center pb-4 lg:hidden">
        <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-line bg-white/95 p-1 shadow-lg shadow-slate-900/10 backdrop-blur">
          {tabs.map(({ value, label, Icon }) => {
            const active = mobileView === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setMobileView(value)}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold transition-colors",
                  active ? "bg-tier1 text-white" : "text-slate-600 hover:bg-slate-100",
                )}
              >
                <Icon size={16} />
                {label}
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
