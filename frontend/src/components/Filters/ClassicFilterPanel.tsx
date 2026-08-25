"use client";

import { useEffect, useRef } from "react";
import { ArrowUpDown, Car, MapPin, WashingMachine } from "lucide-react";

import { useSearchStore } from "@/store/useSearchStore";

// Canonical neighborhood names, mirroring the anchors baked into the
// synthetic dataset (backend/app/data/synthetic_generator.py NEIGHBORHOOD_ANCHORS).
const NEIGHBORHOODS = [
  "سعادت‌آباد",
  "شهرک غرب",
  "یوسف‌آباد",
  "امیرآباد",
  "فاطمی",
  "صادقیه",
  "پونک",
  "جنت‌آباد",
  "میدان انقلاب",
  "دانشگاه شریف",
  "تهرانپارس",
  "نارمک",
];

const MAX_DEPOSIT = 2_000_000_000;
const MAX_RENT = 80_000_000;
const MAX_AREA = 200;

function formatToman(value: number): string {
  if (value <= 0) return "بدون محدودیت";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} میلیارد`;
  return `${Math.round(value / 1_000_000)} میلیون`;
}

export default function ClassicFilterPanel() {
  const {
    depositToman,
    rentToman,
    minAreaSqm,
    hasElevator,
    hasParking,
    hasBalcony,
    selectedNeighborhoods,
    setFilters,
    runSearch,
  } = useSearchStore();

  // Slider/checkbox adjustments update the shared search context and
  // debounce-trigger a re-search (docs/FRONTEND_STATE.md SS2, "filters ->
  // search context" direction of the bidirectional sync).
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSearch();
    }, 300);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depositToman, rentToman, minAreaSqm, hasElevator, hasParking, hasBalcony, selectedNeighborhoods]);

  const toggleNeighborhood = (name: string) => {
    const next = selectedNeighborhoods.includes(name)
      ? selectedNeighborhoods.filter((n) => n !== name)
      : [...selectedNeighborhoods, name];
    setFilters({ selectedNeighborhoods: next });
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-4">
      <section>
        <label className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-700">
          <span>سقف ودیعه (رهن کامل)</span>
          <span className="text-tier1">{formatToman(depositToman)} تومان</span>
        </label>
        <input
          type="range"
          min={0}
          max={MAX_DEPOSIT}
          step={10_000_000}
          value={depositToman}
          onChange={(e) => setFilters({ depositToman: Number(e.target.value) })}
          className="w-full accent-tier1"
        />
      </section>

      <section>
        <label className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-700">
          <span>سقف اجاره ماهیانه</span>
          <span className="text-tier1">{formatToman(rentToman)} تومان</span>
        </label>
        <input
          type="range"
          min={0}
          max={MAX_RENT}
          step={1_000_000}
          value={rentToman}
          onChange={(e) => setFilters({ rentToman: Number(e.target.value) })}
          className="w-full accent-tier1"
        />
      </section>

      <section>
        <label className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-700">
          <span className="flex items-center gap-1">
            <ArrowUpDown size={14} /> حداقل متراژ
          </span>
          <span className="text-tier1">{minAreaSqm > 0 ? `${minAreaSqm} متر` : "بدون محدودیت"}</span>
        </label>
        <input
          type="range"
          min={0}
          max={MAX_AREA}
          step={5}
          value={minAreaSqm}
          onChange={(e) => setFilters({ minAreaSqm: Number(e.target.value) })}
          className="w-full accent-tier1"
        />
      </section>

      <section className="flex flex-col gap-2">
        <span className="text-sm font-semibold text-slate-700">امکانات</span>
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50">
          <input
            type="checkbox"
            checked={hasElevator}
            onChange={(e) => setFilters({ hasElevator: e.target.checked })}
            className="accent-tier1"
          />
          <ArrowUpDown size={16} className="text-slate-500" />
          آسانسور
        </label>
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50">
          <input
            type="checkbox"
            checked={hasParking}
            onChange={(e) => setFilters({ hasParking: e.target.checked })}
            className="accent-tier1"
          />
          <Car size={16} className="text-slate-500" />
          پارکینگ
        </label>
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50">
          <input
            type="checkbox"
            checked={hasBalcony}
            onChange={(e) => setFilters({ hasBalcony: e.target.checked })}
            className="accent-tier1"
          />
          <WashingMachine size={16} className="text-slate-500" />
          بالکن
        </label>
      </section>

      <section>
        <span className="mb-2 flex items-center gap-1 text-sm font-semibold text-slate-700">
          <MapPin size={14} /> محله‌ها
        </span>
        <div className="flex flex-wrap gap-2">
          {NEIGHBORHOODS.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => toggleNeighborhood(name)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                selectedNeighborhoods.includes(name)
                  ? "border-tier1 bg-tier1 text-white"
                  : "border-slate-300 text-slate-600 hover:border-tier1"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
