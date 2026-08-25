"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import clsx from "clsx";

import { useSearchStore } from "@/store/useSearchStore";
import ListingCard from "./ListingCard";

export default function ListingFeed() {
  const { tier1Results, tier2Results, isLoading, searchError, naturalLanguageSummary, showTier2, toggleTier2 } =
    useSearchStore();

  if (isLoading && tier1Results.length === 0 && tier2Results.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Loader2 className="animate-spin" size={28} />
      </div>
    );
  }

  if (searchError) {
    return <div className="p-4 text-sm text-red-600">{searchError}</div>;
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      {naturalLanguageSummary && (
        <p className="mb-3 rounded-lg bg-tier1-light px-3 py-2 text-sm leading-relaxed text-tier1">
          {naturalLanguageSummary}
        </p>
      )}

      {tier1Results.length === 0 && tier2Results.length === 0 && !isLoading && (
        <p className="p-4 text-center text-sm text-slate-400">نتیجه‌ای یافت نشد. فیلترها را تغییر دهید.</p>
      )}

      <div className="flex flex-col gap-3">
        {tier1Results.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
      </div>

      {tier2Results.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            onClick={toggleTier2}
            className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            <span>سایر گزینه‌ها با تطابق کمتر ({tier2Results.length})</span>
            <ChevronDown size={16} className={clsx("transition-transform", showTier2 && "rotate-180")} />
          </button>

          {showTier2 && (
            <div className="mt-3 flex flex-col gap-3">
              {tier2Results.map((listing) => (
                <ListingCard key={listing.id} listing={listing} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
