"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowUpDown,
  ArrowUpRight,
  Car,
  Footprints,
  Handshake,
  ImageOff,
  MapPin,
  Package,
  Sparkles,
  TrainFront,
  Wallet,
} from "lucide-react";
import clsx from "clsx";

import { imageUrl } from "@/lib/api";
import { useSearchStore } from "@/store/useSearchStore";
import { matchBadgeStyle } from "@/lib/matchColor";
import { fa, faMinutes, faYear, formatToman } from "@/lib/format";
import type { ListingResult } from "@/types";

/** The card's photo. Divar-sized and lazy: a feed page is 30 cards, and the
 * images come from a proxied third-party CDN, so they are fetched only as the
 * card scrolls into view and degrade to a placeholder rather than a broken
 * icon when the CDN refuses. */
function Thumbnail({ source, count }: { source: string | null | undefined; count: number }) {
  const [broken, setBroken] = useState(false);
  const proxied = imageUrl(source);

  if (!proxied || broken) {
    return (
      <div className="flex h-[86px] w-[110px] shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-300">
        <ImageOff size={18} />
      </div>
    );
  }

  return (
    <div className="relative h-[86px] w-[110px] shrink-0 overflow-hidden rounded-xl bg-slate-100">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={proxied}
        alt=""
        loading="lazy"
        decoding="async"
        className="h-full w-full object-cover transition group-hover:scale-[1.03]"
        onError={() => setBroken(true)}
      />
      {count > 1 && (
        <span className="absolute bottom-1 right-1 rounded-full bg-slate-900/65 px-1.5 text-xs font-medium tabular-nums text-white">
          {fa(count)}
        </span>
      )}
    </div>
  );
}

function Fact({ icon: Icon, children }: { icon: typeof Car; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1 text-slate-600">
      <Icon size={13} className="text-slate-500" />
      {children}
    </span>
  );
}

export default function ListingCard({ listing }: { listing: ListingResult }) {
  const router = useRouter();
  const mode = useSearchStore((state) => state.mode);
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);
  const setHoveredListingId = useSearchStore((state) => state.setHoveredListingId);

  /** A plain click picks this property out on the map instead of opening it.
   *
   * Hovering a card used to fly the map, which meant the view drifted under
   * the cursor as the user read down the feed. Now the pointer only lights up
   * the matching pin, and the click is what moves the map -- landing on the
   * property with a "مشاهده ملک" button on it, so opening the details stays a
   * deliberate second step rather than something a stray click does.
   *
   * Modifier and middle clicks are left alone, so ⌘/Ctrl-click and "open in
   * new tab" still reach the property's own page the way they do anywhere
   * else on the web. */
  const handleClick = (event: React.MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    // Clicking the focused card again is the way back: it releases the
    // selection, and the map returns to the area the search was run against.
    setSelectedListingId(selectedListingId === listing.id ? null : listing.id);
  };

  const isSelected = selectedListingId === listing.id;
  const matchPercent = Math.round(listing.utility_score * 100);
  // Map-explore results are a plain filter, not a ranked score -- a
  // "% تطابق" badge would misleadingly read as "0% match" for every result.
  const showMatchBadge = mode !== "map";
  const suggestedDeposit = listing.suggested_deposit_toman;
  const suggestedRent = listing.suggested_rent_toman;

  return (
    // Still a real link even though a plain click is intercepted below: the
    // href is what makes ⌘/Ctrl-click, middle-click and "open in new tab"
    // reach the property's own page, and what a screen reader announces.
    <Link
      href={`/listing/${encodeURIComponent(listing.id)}`}
      scroll={false}
      onMouseEnter={() => setHoveredListingId(listing.id)}
      onMouseLeave={() => setHoveredListingId(null)}
      onClick={handleClick}
      className={clsx(
        "group block cursor-pointer rounded-2xl border bg-white p-4 transition-all",
        isSelected
          ? "border-brand shadow-md shadow-brand/10 ring-1 ring-brand/25"
          : "border-line hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md hover:shadow-slate-200/60",
      )}
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <h3 className="text-base font-bold leading-7 text-slate-900">{listing.title}</h3>
        <div className="flex shrink-0 items-center gap-1">
          {showMatchBadge && listing.is_pareto_optimal && (
            <span
              className="flex items-center gap-0.5 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-bold text-amber-600"
              title="هیچ گزینه‌ی دیگری همزمان ارزان‌تر، نزدیک‌تر به مترو و بزرگ‌تر نیست"
            >
              <Sparkles size={10} /> بهینه
            </span>
          )}
          {showMatchBadge && (
            <span
              className="rounded-full px-2 py-0.5 text-xs font-bold tabular-nums"
              style={matchBadgeStyle(listing.utility_score)}
            >
              ٪{matchPercent}
            </span>
          )}
        </div>
      </div>

      <p className="mb-3 flex items-center gap-1 text-xs text-slate-500">
        <MapPin size={12} className="text-slate-400" />
        {listing.neighborhood}
        {listing.district && <span> · {listing.district}</span>}
      </p>

      <div className="mb-3 flex items-start gap-3">
        <Thumbnail source={listing.thumbnail_url} count={listing.image_count} />
        {/* The price panel and, under it, the تبدیل note -- one column, so the
            note stays attached to the figures it is about while living outside
            the panel's frame. Inside it, the note was a third row that only
            some cards had, so the tinted box changed height card to card and
            the feed's rhythm went with it. */}
        <div className="flex min-w-0 flex-1 flex-col gap-1 self-stretch">
        {/* The price sits in a tinted panel rather than between two hairlines:
            it is the one number the eye goes to first, and a pair of rules
            next to the photo read as a stray table edge. */}
        <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 rounded-xl bg-slate-50 px-3.5 py-2 ring-1 ring-line-soft">
        {/* One figure per row, label at the start and amount at the end.
            Side by side they were 260px of bold type in a 246px panel, so
            whether a card showed its price on one line or two came down to how
            many digits it happened to have -- the column never lined up twice
            in a row. */}
        {listing.is_full_rahn ? (
          <div className="flex items-baseline justify-between gap-3">
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <Wallet size={13} className="text-slate-400" />
              رهن کامل
            </span>
            <span className="text-base font-extrabold text-slate-900">{formatToman(listing.deposit_toman)}</span>
          </div>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs text-slate-500">ودیعه</span>
              <span className="text-base font-extrabold text-slate-900">{formatToman(listing.deposit_toman)}</span>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs text-slate-500">اجاره</span>
              <span className="text-base font-extrabold text-slate-900">{formatToman(listing.rent_toman)}</span>
            </div>
          </>
        )}

        </div>

        {/* The advertised split did not fit the budget but a تبدیل does. Showing
            the converted figures next to the advertised ones is what keeps an
            apparently over-budget result from looking like a ranking bug. */}
        {suggestedDeposit != null && suggestedRent != null && (
          <p className="flex min-w-0 items-start gap-1 px-1 text-[11px] leading-4 text-note">
            <Handshake size={11} className="mt-0.5 shrink-0" />
            {/* Wraps to a second line rather than running on: nowrap text here
                has a min-content width wider than the card, and a flex item
                that wide drags the whole feed column out with it -- every card
                in the list then sat a few pixels off the padding. */}
            <span className="min-w-0 break-words">
              با تبدیل: {formatToman(suggestedDeposit)} ودیعه و {formatToman(suggestedRent)} اجاره
            </span>
          </p>
        )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-xs">
        <Fact icon={ArrowUpDown}>{fa(listing.area_sqm)} متر</Fact>
        <Fact icon={Footprints}>{faMinutes(listing.dist_to_metro_mins)} تا مترو</Fact>
        {listing.commute_to_work_mins != null && (
          <Fact icon={TrainFront}>{faMinutes(listing.commute_to_work_mins)} تا محل کار</Fact>
        )}
        {listing.build_year != null && <Fact icon={Sparkles}>ساخت {faYear(listing.build_year)}</Fact>}
        {listing.has_elevator && <Fact icon={ArrowUpDown}>آسانسور</Fact>}
        {listing.has_parking && <Fact icon={Car}>پارکینگ</Fact>}
        {listing.has_storage && <Fact icon={Package}>انباری</Fact>}
      </div>

      {listing.trade_off_rationale && (
        <p className="mt-3 rounded-xl bg-note-light px-3 py-2 text-xs leading-5 text-note">
          {listing.trade_off_rationale}
        </p>
      )}

      {/* Selecting and opening stay two separate gestures, but the second one
          is offered here rather than on the map pin: the button belongs to the
          property the user is reading. The click must not bubble up to the
          card's own handler, which would release the selection instead. */}
      {isSelected && (
        <button
          type="button"
          onClick={(event) => {
            // Both are needed: stopPropagation keeps the card's own handler
            // from releasing the selection, and preventDefault stops the
            // surrounding <a> from doing a full navigation to the property
            // page -- which is what made this button leave the search instead
            // of opening the popup over it. The popup carries its own
            // "صفحهٔ کامل" link for opening the page in a new tab.
            event.stopPropagation();
            event.preventDefault();
            router.push(`/listing/${encodeURIComponent(listing.id)}`, { scroll: false });
          }}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-brand py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand/90"
        >
          <ArrowUpRight size={15} />
          مشاهده ملک
        </button>
      )}
    </Link>
  );
}
