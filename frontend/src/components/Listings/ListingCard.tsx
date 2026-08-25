"use client";

import { ArrowUpDown, Car, Footprints, TrainFront } from "lucide-react";
import clsx from "clsx";

import { useSearchStore } from "@/store/useSearchStore";
import type { ListingResult } from "@/types";

function formatToman(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} میلیارد`;
  if (value >= 1_000_000) return `${Math.round(value / 1_000_000).toLocaleString("fa-IR")} میلیون`;
  return value.toLocaleString("fa-IR");
}

export default function ListingCard({ listing }: { listing: ListingResult }) {
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);
  const setHoveredListingId = useSearchStore((state) => state.setHoveredListingId);

  const isTier1 = listing.tier === 1;
  const isSelected = selectedListingId === listing.id;
  const matchPercent = Math.round(listing.utility_score * 100);

  return (
    <article
      onMouseEnter={() => setHoveredListingId(listing.id)}
      onMouseLeave={() => setHoveredListingId(null)}
      onClick={() => setSelectedListingId(listing.id)}
      className={clsx(
        "cursor-pointer rounded-xl border bg-white p-3 shadow-sm transition-all hover:shadow-md",
        isSelected ? "border-tier1 ring-2 ring-tier1/30" : "border-slate-200",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold leading-snug text-slate-800">{listing.title}</h3>
        <span
          className={clsx(
            "shrink-0 rounded-full px-2 py-0.5 text-xs font-bold",
            isTier1 ? "bg-tier1-light text-tier1" : "bg-tier2-light text-tier2",
          )}
        >
          %{matchPercent} تطابق
        </span>
      </div>

      <p className="mb-2 text-xs text-slate-500">{listing.neighborhood}</p>

      <div className="mb-2 flex items-baseline gap-3 text-sm">
        <span className="font-bold text-slate-800">{formatToman(listing.deposit_toman)}</span>
        <span className="text-slate-400">ودیعه</span>
        <span className="font-bold text-slate-800">{formatToman(listing.rent_toman)}</span>
        <span className="text-slate-400">اجاره</span>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
        <span className="flex items-center gap-1">
          <ArrowUpDown size={13} /> {listing.area_sqm} متر
        </span>
        <span className="flex items-center gap-1">
          <Footprints size={13} /> {listing.dist_to_metro_mins.toFixed(0)} دقیقه تا مترو
        </span>
        {listing.commute_to_work_mins != null && (
          <span className="flex items-center gap-1">
            <TrainFront size={13} /> {listing.commute_to_work_mins.toFixed(0)} دقیقه تا محل کار
          </span>
        )}
        {listing.has_elevator && (
          <span className="flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5">
            <ArrowUpDown size={12} /> آسانسور
          </span>
        )}
        {listing.has_parking && (
          <span className="flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5">
            <Car size={12} /> پارکینگ
          </span>
        )}
      </div>

      {listing.trade_off_rationale && (
        <p className="mt-2 rounded-lg bg-tier2-light px-2 py-1.5 text-xs text-tier2">{listing.trade_off_rationale}</p>
      )}
    </article>
  );
}
