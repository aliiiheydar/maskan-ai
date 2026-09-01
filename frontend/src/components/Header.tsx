"use client";

import { Building2, ChevronDown, Map, MapPin, Sparkles, SlidersHorizontal } from "lucide-react";

import { useSearchStore } from "@/store/useSearchStore";
import type { SearchMode } from "@/types";

/** The three ways to search, in the order they matter.
 *
 * فیلتر کلاسیک is the product; it leads. The conversational search is a real
 * feature but an early one -- its extraction is still being tuned -- so it
 * carries a بتا badge rather than being offered as an equal, and the map is
 * exploration rather than a way to state what you want. */
const MODES: {
  value: SearchMode;
  label: string;
  Icon: typeof Sparkles;
  badge?: string;
  /** Not offered on a phone.
   *
   * Map-explore is the two columns read against each other; on a phone they
   * are separate tabs, so the mode has nothing left to be. app/page.tsx hands
   * a narrowed window back to the filters for the same reason. */
  desktopOnly?: boolean;
}[] = [
  { value: "classic", label: "فیلتر کلاسیک", Icon: SlidersHorizontal },
  { value: "intelligent", label: "جستجوی هوشمند", Icon: Sparkles, badge: "بتا" },
  { value: "map", label: "کاوش نقشه", Icon: Map, desktopOnly: true },
];

/** The city picker.
 *
 * Only Tehran exists: the transit graph, the congestion zones, the
 * neighborhood polygons and the price model are all Tehran's. It is shown
 * anyway -- and shown as a real control rather than a caption -- because the
 * map is now hard-bounded to the city, and a user who cannot pan out of
 * Tehran should be able to see *why* without guessing. The other options are
 * listed as disabled so the answer to "can I search Karaj?" is on screen.
 */
function CitySelect() {
  return (
    <label className="relative flex shrink-0 items-center gap-1.5 rounded-full bg-slate-100 py-1.5 pe-2 ps-3 text-sm font-medium text-slate-700 transition hover:bg-slate-200/70">
      <MapPin size={14} className="text-tier1" />
      <span className="sr-only">شهر</span>
      <select
        // Transparent over the pill rather than a styled <select> box: a
        // native dropdown arrow plus our own chevron would draw two.
        className="cursor-pointer appearance-none bg-transparent pe-4 outline-none"
        value="tehran"
        onChange={() => undefined}
      >
        <option value="tehran">تهران</option>
        <option value="karaj" disabled>
          کرج (به‌زودی)
        </option>
        <option value="mashhad" disabled>
          مشهد (به‌زودی)
        </option>
      </select>
      {/* At the *end* of the pill, which is where the select's own `pe-4`
          reserves the room for it. Pinned to `start-2` it sat on top of the
          MapPin and the first letters of the city name instead. */}
      <ChevronDown size={13} className="pointer-events-none absolute end-2 text-slate-500" />
    </label>
  );
}

export default function Header() {
  const mode = useSearchStore((state) => state.mode);
  const setMode = useSearchStore((state) => state.setMode);

  return (
    // Nothing here is allowed to push the bar wider than the window. At 360px
    // the brand, the city pill and the mode switch together came to more than
    // the screen, and the overflow -- in RTL, off the near edge -- shifted
    // every column under it. The identity block is the one part that can give
    // way, so it is the only one that shrinks.
    <header className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-white/90 px-3 py-2.5 backdrop-blur sm:gap-4 sm:px-6">
      <div className="flex min-w-0 shrink items-center gap-2 sm:gap-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-tier1 text-white shadow-sm shadow-tier1/25">
          <Building2 size={19} />
        </div>
        <div className="min-w-0 leading-tight">
          <span className="block truncate text-base font-bold text-slate-800">مسکن‌یار</span>
          <span className="hidden text-xs text-slate-500 sm:block">اجارهٔ خانه، هوشمند</span>
        </div>
        <span className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" />
        <CitySelect />
      </div>

      <nav className="flex shrink-0 items-center gap-0.5 rounded-full bg-slate-100 p-1 text-sm font-medium">
        {MODES.map(({ value, label, Icon, badge, desktopOnly }) => {
          const active = mode === value;
          return (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              aria-current={active ? "page" : undefined}
              title={badge ? `${label} (${badge})` : label}
              className={`items-center gap-1.5 rounded-full px-2.5 py-1.5 transition-all sm:px-3 ${
                desktopOnly ? "hidden lg:flex" : "flex"
              } ${active ? "bg-white text-tier1 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
            >
              <Icon size={15} />
              <span className="hidden sm:inline">{label}</span>
              {badge && (
                // A dot where the label is hidden: the badge has to survive
                // the narrow layout, or the one mode that comes with a caveat
                // loses it on exactly the screens that get no tooltip either.
                <>
                  <span className="hidden rounded-full bg-amber-100 px-1.5 py-px text-xs font-bold text-amber-700 sm:inline">
                    {badge}
                  </span>
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500 sm:hidden" aria-hidden />
                </>
              )}
            </button>
          );
        })}
      </nav>
    </header>
  );
}
