"use client";

import { ArrowUp, Loader2, SearchX } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSearchStore } from "@/store/useSearchStore";
import ListingCard from "./ListingCard";

/** Card-shaped placeholders during the first load. A spinner on an empty
 * panel reads as "nothing here"; these read as "results are coming". */
function FeedSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-5">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="animate-pulse rounded-2xl border border-line bg-white p-4">
          <div className="mb-3 h-4 w-2/3 rounded bg-slate-100" />
          <div className="mb-4 h-3 w-1/3 rounded bg-slate-100" />
          <div className="h-8 rounded-lg bg-slate-50" />
        </div>
      ))}
    </div>
  );
}

export default function ListingFeed() {
  const {
    mode,
    tier1Results,
    tier2Results,
    totalCount,
    isLoading,
    isLoadingMore,
    searchError,
    loadMoreResults,
  } = useSearchStore();

  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const focusedListing = useSearchStore((state) => state.focusedListing);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);

  const loadedCount = tier1Results.length + tier2Results.length;
  const hasMore = loadedCount < totalCount;
  const isEmpty = loadedCount === 0;

  // A pin selected from a part of the map the feed has not paged in yet is
  // appended here (see focusedListing), so every pin has a card to scroll to.
  const ranked = useMemo(() => {
    const loaded = [...tier1Results, ...tier2Results];
    if (focusedListing && !loaded.some((listing) => listing.id === focusedListing.id)) {
      loaded.push(focusedListing);
    }
    return loaded;
  }, [tier1Results, tier2Results, focusedListing]);

  /** Selecting a property anywhere -- a card, or its pin on the map -- brings
   * it into view here, so the map flying to a pin and the feed showing that
   * pin's card are one gesture rather than two the user has to connect. */
  const cardNodes = useRef(new Map<string, HTMLElement>());
  const registerCard = (id: string, node: HTMLElement | null) => {
    if (node) cardNodes.current.set(id, node);
    else cardNodes.current.delete(id);
  };
  useEffect(() => {
    if (!selectedListingId) return;
    cardNodes.current.get(selectedListingId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [selectedListingId, ranked]);

  /** Back to the top of the results.
   *
   * While a property is in focus the list is parked on that card and the map
   * on its pin, so jumping to the top without letting go of it would leave the
   * two showing different things. Deselecting first is what makes this one
   * gesture: the map flies back to the search area on its own (NeshanMap's
   * FocusedListingFly watches for the selection clearing), and the list then
   * returns to the beginning.
   *
   * Shown on scroll position alone. It used to appear for any selection too,
   * which meant picking the first card in the list -- with the list already at
   * the top -- produced a button offering to take the user somewhere they
   * already were. */
  const scrollBox = useRef<HTMLDivElement>(null);
  const [isScrolled, setIsScrolled] = useState(false);
  const backToTop = () => {
    if (selectedListingId) setSelectedListingId(null);
    scrollBox.current?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const showBackToTop = isScrolled;

  if (isLoading && isEmpty) return <FeedSkeleton />;

  if (searchError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <SearchX size={26} className="text-red-300" />
        <p className="text-sm text-red-600">{searchError}</p>
      </div>
    );
  }

  return (
    // `w-full`: the feed is a flex *item* in the page's row, so its width is
    // its content's unless it is told otherwise. That let a single wide card
    // -- or, with no cards at all, a short empty-state -- decide how wide the
    // column drew, which is why "نتیجه‌ای یافت نشد" sat off to one side
    // instead of in the middle of the panel.
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-white px-5 py-3">
        {/* What the list is, and what order it is in. The ranking was doing
            real work that the feed never named, so the ٪ badges read as
            decoration rather than as the sort key they are. */}
        {/* Two facts, visibly two. They used to be adjacent inline spans held
            apart by a margin, and at this type size Persian closes an 8px gap
            on its own: «۱۷٬۱۵۸ ملک» ran straight into «مرتب‌شده…» as one word.
            A flex row with a dot between them cannot read as anything else. */}
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 text-sm font-semibold text-slate-700">
            {totalCount > 0 ? `${totalCount.toLocaleString("fa-IR")} ملک` : "نتایج"}
          </span>
          <span aria-hidden className="h-1 w-1 shrink-0 rounded-full bg-slate-300" />
          <span className="truncate text-xs text-slate-500">
            {mode === "map" ? "در محدودهٔ نقشه" : "مرتب‌شده بر اساس میزان تطابق"}
          </span>
        </div>
        {isLoading && <Loader2 className="animate-spin text-slate-300" size={15} />}
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col">
        {/* Floating rather than pinned in the header: it is a way out of a
            scrolled or focused list, so it appears when there is something to
            come back from and stays invisible otherwise. */}
        <button
          type="button"
          onClick={backToTop}
          aria-label="بازگشت به ابتدای فهرست"
          className={`absolute top-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-slate-900/90 px-3 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur transition-all duration-200 hover:bg-slate-900 ${
            showBackToTop ? "pointer-events-auto opacity-100" : "pointer-events-none -translate-y-2 opacity-0"
          }`}
        >
          <ArrowUp size={13} />
          ابتدای فهرست
        </button>

        <div
          ref={scrollBox}
          onScroll={(e) => setIsScrolled(e.currentTarget.scrollTop > 200)}
          // pb-24 on a phone: the floating view switcher (see app/page.tsx)
          // hovers over the bottom of this column and would otherwise cover
          // the last card and the "نمایش موارد بیشتر" button.
          // overflow-x-hidden pins the scrolling to one axis: a `visible`
          // axis beside a scrolling one computes to `auto`, so a single wide
          // child (a long title, a wide fact row) quietly made this column
          // horizontally scrollable, and in RTL the surplus hangs off the far
          // edge -- every card then sat a few pixels out of line with the
          // padding on the near side.
          className="flex-1 overflow-y-auto overflow-x-hidden p-4 pb-24 sm:p-5 sm:pb-24 lg:pb-5"
        >
        {/* What this mode is, where the user is already looking. Map-explore
            returns everything inside the viewport regardless of the filter
            panel, and that is surprising enough to be worth one line. */}
        {mode === "map" && (
          <p className="mb-3 rounded-xl bg-slate-50 px-3.5 py-2.5 text-xs leading-6 text-slate-500 ring-1 ring-line">
            نقشه را بکشید یا زوم کنید تا همهٔ املاک همان محدوده نمایش داده شوند. در این حالت فیلترها اعمال نمی‌شوند.
          </p>
        )}

        {isEmpty && !isLoading && (
          <div className="flex w-full flex-col items-center gap-2 py-16 text-center">
            <SearchX size={26} className="text-slate-300" />
            <p className="text-sm text-slate-500">نتیجه‌ای یافت نشد.</p>
            <p className="text-xs text-slate-500">
              {mode === "map" ? "نقشه را جابه‌جا کنید یا زوم را کم کنید." : "فیلترها را کمی بازتر کنید."}
            </p>
          </div>
        )}

        {/* One ranked list, not a strong list plus a folded-away weak one. The
            ٪ badge already says how well each result matches, so a "سایر
            گزینه‌ها" header only restated it as a wall the user had to click
            through; the "نمایش بیشتر" button below is the one control the feed
            needs. */}
        <div className="flex min-w-0 flex-col gap-3">
          {ranked.map((listing) => (
            <div key={listing.id} ref={(node) => registerCard(listing.id, node)}>
              <ListingCard listing={listing} />
            </div>
          ))}
        </div>

        {hasMore && (
          <button
            type="button"
            onClick={loadMoreResults}
            disabled={isLoadingMore}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border border-line bg-white py-3 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            {isLoadingMore && <Loader2 className="animate-spin" size={15} />}
            نمایش موارد بیشتر
            <span className="text-slate-500">
              ({loadedCount.toLocaleString("fa-IR")} از {totalCount.toLocaleString("fa-IR")})
            </span>
          </button>
        )}
        </div>
      </div>
    </div>
  );
}
