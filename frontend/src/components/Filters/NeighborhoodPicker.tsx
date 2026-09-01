"use client";

import { useEffect, useMemo, useState } from "react";
import { Crosshair, MapPin, Search, X } from "lucide-react";

import { useSearchStore } from "@/store/useSearchStore";
import type { NeighborhoodSummary } from "@/types";

/** Long enough to be a search, short enough not to scroll forever. */
const MAX_SUGGESTIONS = 30;

/** Persian text typed by a user rarely matches stored text byte-for-byte:
 * ZWNJ, the Arabic yeh/kaf and stray spaces all differ. Matching happens on a
 * form with those flattened away -- the same normalization the backend applies
 * when it resolves a name onto a polygon. */
function normalize(text: string): string {
  return text
    .replace(/‌/g, "")
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\s+/g, "")
    .trim();
}

export default function NeighborhoodPicker() {
  const catalog = useSearchStore((state) => state.neighborhoodCatalog);
  const loadNeighborhoods = useSearchStore((state) => state.loadNeighborhoods);
  const selected = useSearchStore((state) => state.selectedNeighborhoods);
  const isPickingNeighborhood = useSearchStore((state) => state.isPickingNeighborhood);
  const setFilters = useSearchStore((state) => state.setFilters);
  const [query, setQuery] = useState("");
  // The list of 258 neighborhoods would otherwise push every other filter
  // below the fold, so it only opens once the user is actually choosing one.
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    void loadNeighborhoods();
  }, [loadNeighborhoods]);

  const byKey = useMemo(() => new Map(catalog.map((n) => [n.key, n])), [catalog]);

  const suggestions = useMemo<NeighborhoodSummary[]>(() => {
    const needle = normalize(query);
    const pool = catalog.filter((n) => !selected.includes(n.key));
    if (!needle) return pool.slice(0, MAX_SUGGESTIONS);
    // Subtitles list the streets and landmarks inside a neighborhood, which is
    // how most people describe where they want to live ("نزدیک میدان ونک")
    // rather than by the neighborhood's own name.
    return pool
      .filter((n) => normalize(n.title).includes(needle) || normalize(n.subtitle).includes(needle))
      .slice(0, MAX_SUGGESTIONS);
  }, [catalog, selected, query]);

  const add = (key: string) => {
    setFilters({ selectedNeighborhoods: [...selected, key] });
    setQuery("");
  };

  const remove = (key: string) => {
    setFilters({ selectedNeighborhoods: selected.filter((k) => k !== key) });
  };

  return (
    <div className="flex flex-col gap-2">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => remove(key)}
              className="group flex items-center gap-1 rounded-full bg-tier1 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-tier1/85"
            >
              {byKey.get(key)?.title ?? key}
              <X size={12} className="opacity-70 group-hover:opacity-100" />
            </button>
          ))}
          <button
            type="button"
            onClick={() => setFilters({ selectedNeighborhoods: [] })}
            className="rounded-full px-2 py-1 text-xs text-slate-500 transition-colors hover:text-red-500"
          >
            حذف همه
          </button>
        </div>
      )}

      {/* Naming a محله and pointing at one are the same choice made two ways:
          people who know the name type it, people who know the map click it.
          Both write into the same selection, so a neighborhood picked on the
          map appears as a chip here and can be removed the same way. */}
      <button
        type="button"
        onClick={() => setFilters({ isPickingNeighborhood: !isPickingNeighborhood })}
        className={`flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
          isPickingNeighborhood
            ? "border-tier1 bg-tier1 text-white"
            : "border-line text-slate-600 hover:border-tier1"
        }`}
      >
        <Crosshair size={14} />
        {isPickingNeighborhood ? "روی نقشه کلیک کنید..." : "انتخاب محله روی نقشه"}
      </button>

      <div className="relative">
        <Search size={14} className="pointer-events-none absolute end-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsOpen(true)}
          // Deferred so a click on a suggestion lands before the list closes.
          onBlur={() => setTimeout(() => setIsOpen(false), 150)}
          placeholder="جستجوی محله یا خیابان..."
          className="w-full rounded-xl border border-line bg-slate-50 py-2 pe-8 ps-3 text-sm outline-none transition-colors focus:border-tier1 focus:bg-white"
        />
      </div>

      {!isOpen && !query ? null : catalog.length === 0 ? (
        <p className="px-1 text-xs text-slate-500">در حال بارگذاری محله‌ها...</p>
      ) : suggestions.length === 0 ? (
        <p className="px-1 text-xs text-slate-500">محله‌ای با این نام پیدا نشد.</p>
      ) : (
        <ul className="max-h-56 overflow-y-auto overflow-x-hidden rounded-xl border border-line-soft">
          {suggestions.map((neighborhood) => (
            <li key={neighborhood.key}>
              <button
                type="button"
                onClick={() => add(neighborhood.key)}
                className="flex w-full items-start gap-2 border-b border-line-soft px-3 py-2 text-right transition-colors last:border-b-0 hover:bg-slate-50"
              >
                <MapPin size={13} className="mt-0.5 shrink-0 text-slate-300" />
                {/* Wrapping, not truncating. The subtitle is the list of
                    streets and landmarks people actually search by, and it is
                    routinely longer than this column: cut to one line it told
                    the user nothing, and left un-cut its nowrap min-content
                    width pushed the whole filter panel wider than the layout
                    it sits in. */}
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-sm text-slate-700">{neighborhood.title}</span>
                  {neighborhood.subtitle && (
                    <span className="block break-words text-[11px] leading-5 text-slate-500">{neighborhood.subtitle}</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
