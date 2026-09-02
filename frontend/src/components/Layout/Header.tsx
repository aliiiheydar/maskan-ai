"use client";

import { Building2, ChevronDown, Map, MapPin, Sparkles, SlidersHorizontal } from "lucide-react";

import { useSearchStore } from "@/store/useSearchStore";
import type { SearchMode } from "@/types";

/** The three ways to search, in the order they matter.
 *
 * جستجو و رتبه‌بندی is the product; it leads. The name is the feature: the
 * panel does not merely filter, it scores every match against what the user
 * asked for and orders the list by it, and calling that "فیلتر کلاسیک" sold
 * the one thing this app does that Divar does not as the boring option.
 *
 * The conversational search is a real feature but an early one -- its
 * extraction is still being tuned -- so it carries a بتا badge rather than
 * being offered as an equal, and it is named for what it is (you talk to it)
 * rather than for being the "smart" one: the ranking is where the intelligence
 * lives, and it runs underneath both. The map is exploration rather than a way
 * to state what you want. */
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
  { value: "ranked", label: "جستجو و رتبه‌بندی", Icon: SlidersHorizontal },
  { value: "chat", label: "جستجوی گفت‌وگویی", Icon: Sparkles, badge: "بتا" },
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
      <MapPin size={14} className="text-brand" />
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
  const aiSearchEnabled = useSearchStore((state) => state.aiSearchEnabled);
  const exploreMapEnabled = useSearchStore((state) => state.exploreMapEnabled);

  // کاوش نقشه is dropped rather than disabled when a deployment turns it off.
  // The AI mode below is greyed out because something is missing that could be
  // supplied; this one is a decision about what the product is, and a mode
  // nobody can ever reach is just clutter in a three-item switch.
  const modes = exploreMapEnabled ? MODES : MODES.filter(({ value }) => value !== "map");

  return (
    // Nothing here is allowed to push the bar wider than the window. At 360px
    // the brand, the city pill and the mode switch together came to more than
    // the screen, and the overflow -- in RTL, off the near edge -- shifted
    // every column under it. The identity block is the one part that can give
    // way, so it is the only one that shrinks.
    <header className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-white/90 px-3 py-2.5 backdrop-blur sm:gap-4 sm:px-6">
      <div className="flex min-w-0 shrink items-center gap-2 sm:gap-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-sm shadow-brand/25">
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
        {modes.map(({ value, label, Icon, badge, desktopOnly }) => {
          const active = mode === value;
          // The conversational mode is the one thing here that a deployment
          // can be missing (it needs an OpenRouter key). Shown, not hidden --
          // its absence would look like a feature that was never built --
          // but visibly unavailable, and saying so in the tooltip, which is
          // the only place there is room to say why.
          const disabled = value === "chat" && !aiSearchEnabled;
          const shownBadge = disabled ? "غیرفعال" : badge;
          return (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              disabled={disabled}
              aria-current={active ? "page" : undefined}
              title={
                disabled
                  ? "جستجوی گفت‌وگویی روی این سرور پیکربندی نشده است؛ از پنل جستجو و رتبه‌بندی استفاده کنید."
                  : badge
                    ? `${label} (${badge})`
                    : label
              }
              className={`items-center gap-1.5 rounded-full px-2.5 py-1.5 transition-all sm:px-3 ${
                desktopOnly ? "hidden lg:flex" : "flex"
              } ${
                disabled
                  ? "cursor-not-allowed text-slate-400"
                  : active
                    ? "bg-white text-brand shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Icon size={15} />
              <span className="hidden sm:inline">{label}</span>
              {shownBadge && (
                // A dot where the label is hidden: the badge has to survive
                // the narrow layout, or the one mode that comes with a caveat
                // loses it on exactly the screens that get no tooltip either.
                <>
                  <span
                    className={`hidden rounded-full px-1.5 py-px text-xs font-bold sm:inline ${
                      disabled ? "bg-slate-200 text-slate-500" : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {shownBadge}
                  </span>
                  <span
                    className={`h-1.5 w-1.5 rounded-full sm:hidden ${disabled ? "bg-slate-400" : "bg-amber-500"}`}
                    aria-hidden
                  />
                </>
              )}
            </button>
          );
        })}
      </nav>
    </header>
  );
}
