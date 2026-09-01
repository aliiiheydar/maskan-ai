"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Maximize2, X } from "lucide-react";

import ListingDetailLoader from "@/components/Listings/ListingDetail";

/**
 * The listing detail as an overlay above the search.
 *
 * Opening a property should not cost the user the search they built -- the
 * filters, the ranked feed and the map viewport are all still there behind
 * this. It is nevertheless a real route (`/listing/<id>`), reached through an
 * intercepting route, so the URL is shareable, a refresh renders the full
 * page instead of an empty overlay, and ⌘/Ctrl-click still opens a new tab.
 * Closing is a history `back()`, which is what makes the browser's own back
 * button dismiss it.
 *
 * The chrome is deliberately unlike the standalone page's: a floating toolbar
 * over the photo rather than a header above it, so the overlay reads as a
 * quick look at one result and the page reads as the property's own page.
 */
export default function ListingModal({ id }: { id: string }) {
  const router = useRouter();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") router.back();
    };
    window.addEventListener("keydown", onKey);
    // The page underneath is a full-height app shell; letting it scroll behind
    // the overlay makes the map and the feed drift while the dialog is open.
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [router]);

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-start justify-center overflow-y-auto bg-slate-900/50 p-3 backdrop-blur-[3px] sm:p-8"
      role="dialog"
      aria-modal="true"
      onClick={(event) => {
        if (event.target === event.currentTarget) router.back();
      }}
    >
      <div className="relative my-auto w-full max-w-3xl">
        {/* The controls float above the content rather than reserving a strip
            of their own: the photo is what the user came to see, and a header
            band would push it below the fold on a laptop. */}
        <div className="pointer-events-none sticky top-0 z-10 -mb-[52px] flex justify-between p-3">
          <a
            href={`/listing/${encodeURIComponent(id)}`}
            target="_blank"
            rel="noopener noreferrer"
            title="باز کردن در صفحهٔ کامل"
            className="pointer-events-auto flex items-center gap-1.5 rounded-full bg-white/90 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-lg ring-1 ring-slate-900/5 backdrop-blur transition hover:bg-white hover:text-slate-900"
          >
            <Maximize2 size={12} />
            صفحهٔ کامل
          </a>
          <button
            type="button"
            onClick={() => router.back()}
            aria-label="بستن"
            className="pointer-events-auto rounded-full bg-white/90 p-2 text-slate-500 shadow-lg ring-1 ring-slate-900/5 backdrop-blur transition hover:bg-white hover:text-slate-900"
          >
            <X size={16} />
          </button>
        </div>

        <div className="rounded-3xl bg-white p-4 shadow-2xl ring-1 ring-slate-900/5 sm:p-6">
          <ListingDetailLoader id={id} variant="modal" />
        </div>
      </div>
    </div>
  );
}
