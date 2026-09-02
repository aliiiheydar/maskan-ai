"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  Bookmark,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Compass,
  ExternalLink,
  Flame,
  Footprints,
  Handshake,
  Home,
  Layers,
  ListTree,
  MapPin,
  Minus,
  PawPrint,
  Ruler,
  Share2,
  Snowflake,
  Sofa,
  Sparkles,
  Text,
  TrainFront,
  Users,
  Wallet,
} from "lucide-react";
import clsx from "clsx";

import ListingGallery from "@/components/Listings/ListingGallery";
import { getListing } from "@/lib/api";
import { fa, faDigits, faMinutes, faYear, formatToman } from "@/lib/format";
import type { Listing } from "@/types";

/** Leaflet and MapLibre both touch `window` at module scope, so the location
 * map cannot be part of the server render of this page. */
const ListingLocationMap = dynamic(() => import("@/components/Listings/ListingLocationMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-slate-100" />,
});

/** Two presentations of the same property, deliberately not the same page.
 *
 *  - `modal` sits over the search the user built. It is a *preview*: one
 *    column, compact type, and the sections a renter uses to decide whether
 *    this one is worth a closer look.
 *  - `page` is where a shared link, a new tab or a refresh lands, with no
 *    search behind it to preserve. It gets the room: a wide hero gallery,
 *    display-sized headings, and a price card that tracks alongside the
 *    content on a desktop.
 *
 * Both render from this one component, so the two can never disagree about a
 * listing's facts -- only about how much space those facts are given.
 */
export type DetailVariant = "modal" | "page";

const FLOOR_LABEL = (floor: number, total: number) =>
  floor < 0 ? "زیرزمین" : floor === 0 ? `همکف از ${fa(total)}` : `${fa(floor)} از ${fa(total)}`;

const PETS_LABEL: Record<string, string> = {
  allowed: "مجاز",
  not_allowed: "غیرمجاز",
  negotiable: "با توافق",
};

/** Building-equipment facets, in the order a renter cares about. */
const FEATURE_GROUPS: { key: string; label: string; icon: typeof Flame }[] = [
  { key: "cooling", label: "سرمایش", icon: Snowflake },
  { key: "heating", label: "گرمایش", icon: Flame },
  { key: "water_heater", label: "آب گرم", icon: Flame },
  { key: "floor_material", label: "جنس کف", icon: Layers },
  { key: "wc_type", label: "سرویس بهداشتی", icon: Home },
];

/** Advertiser fields the normalised sections above already show.
 *
 * The ad's own table is worth keeping -- it is the only place anything we
 * failed to model survives -- but printing ودیعه and متراژ a second time made
 * it read as a duplicate of the page rather than as the remainder of it.
 * Compared after squashing spaces and ZWNJ, because the same label arrives
 * spelled both ways ("اجارهٔ ماهانه" / "اجاره ماهانه"). */
const ALREADY_SHOWN = new Set(
  [
    // Money -- the price card
    "ودیعه",
    "اجاره ماهانه",
    "اجارهٔ ماهانه",
    "ودیعه و اجاره",
    "قابل تبدیل",
    // Specification grid
    "متراژ",
    "اتاق",
    "تعداد اتاق",
    "طبقه",
    "تعداد کل طبقات ساختمان",
    "تعداد طبقات ساختمان",
    "تعداد واحد در طبقه",
    "واحد در طبقه",
    "سال ساخت",
    "جهت ساختمان",
    "نوع آشپزخانه",
    "حداقل مدت قرارداد",
    // Amenity chips
    "آسانسور",
    "پارکینگ",
    "انباری",
    "بالکن",
    "بازسازی شده",
    "مبله",
    "حیوان خانگی",
    // Building-equipment rows
    "سرمایش",
    "گرمایش",
    "آب گرم",
    "جنس کف",
    "سرویس بهداشتی",
    // Gallery
    "تصویرها برای همین ملک است؟",
  ].map((label) => label.replace(/[‌\s]/g, "")),
);

/** Fields whose value we read out of the ad's prose rather than a field the
 * advertiser filled in. Marking them is the whole point of keeping provenance:
 * a renter should be able to tell a stated fact from an inferred one. */
function DerivedMark({ provenance, field }: { provenance: Record<string, string> | undefined; field: string }) {
  const origin = provenance?.[field];
  if (origin !== "listing_text" && origin !== "estimated_from_area") return null;
  const label = origin === "listing_text" ? "از متن آگهی" : "تخمینی";
  return (
    <span
      className="rounded-full bg-amber-50 px-1.5 py-px text-xs font-medium text-amber-700 ring-1 ring-amber-200/70"
      title={
        origin === "listing_text"
          ? "آگهی‌دهنده این مورد را در فیلدهای آگهی وارد نکرده؛ از متن آگهی استخراج شده است."
          : "بر اساس متراژ تخمین زده شده است."
      }
    >
      {label}
    </span>
  );
}

/** A titled panel with a real edge.
 *
 * Everything on this page used to be white type on white with a 3px accent
 * bar between sections, so a long advert read as one undifferentiated column
 * with pockets of empty space where a short section happened to fall. Each
 * section is now a bordered card whose header names it: the card fills its
 * column whatever its contents, which is what turns the leftover space into
 * structure instead of a gap. */
function Card({
  icon: Icon,
  title,
  hint,
  aside,
  children,
  bodyClassName,
}: {
  icon: typeof Home;
  title: string;
  hint?: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-white">
      <header className="flex items-center justify-between gap-3 border-b border-line-soft bg-slate-50/80 px-4 py-2.5">
        <h3 className="flex items-center gap-2 text-sm font-bold text-slate-800">
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-brand/10 text-brand">
            <Icon size={14} />
          </span>
          {title}
        </h3>
        {aside}
      </header>
      {hint && <p className="border-b border-line-soft bg-amber-50/50 px-4 py-2 text-xs text-amber-800">{hint}</p>}
      <div className={bodyClassName ?? "p-4"}>{children}</div>
    </section>
  );
}

/** One fact in the specification grid.
 *
 * Drawn as a cell of a ruled grid rather than a free-floating tile: the rules
 * carry the eye across a row, which is what a spec table is for, and they cost
 * no vertical space of their own. */
function Spec({
  icon: Icon,
  label,
  value,
  mark,
}: {
  icon: typeof Home;
  label: string;
  value: React.ReactNode;
  mark?: React.ReactNode;
}) {
  return (
    // Label pinned to the start, value to the end: read as a stack the value
    // floated in the middle of a 370px cell and left two thirds of every row
    // empty. Spread across the cell they line up into columns the eye can run
    // down, which is what a specification table is for.
    <div className="flex items-center justify-between gap-3 px-4 py-2.5">
      <span className="flex items-center gap-2 text-sm text-slate-500">
        <Icon size={15} className="text-slate-400" />
        {label}
      </span>
      <span className="flex min-w-0 items-center gap-1.5 text-sm font-bold text-slate-800">
        {mark}
        <span className="truncate">{value}</span>
      </span>
    </div>
  );
}

function Chip({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "green" | "amber" | "blue" | "muted";
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ring-1",
        tone === "green" && "bg-brand-light text-brand ring-brand/20",
        tone === "amber" && "bg-amber-50 text-amber-700 ring-amber-200",
        tone === "blue" && "bg-note-light text-note ring-note/20",
        tone === "slate" && "bg-slate-100 text-slate-700 ring-slate-200",
        // Struck through rather than red: a missing amenity is information,
        // not a fault of the property.
        tone === "muted" && "bg-white text-slate-400 ring-slate-200 line-through decoration-slate-300",
      )}
    >
      {children}
    </span>
  );
}

/** The price, as the one block a renter reads before anything else.
 *
 * ودیعه and اجاره get the largest type on screen against a tinted ground, and
 * the Tabdil-normalised figure sits under them on its own rule because it is
 * the only number on which two differently structured offers compare at all.
 */
function PriceCard({ listing }: { listing: Listing }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-white">
      <div className="bg-gradient-to-bl from-brand/10 via-brand/5 to-transparent px-4 py-3.5">
        {listing.is_full_rahn ? (
          <div>
            <p className="text-xs font-semibold text-brand">رهن کامل</p>
            <p className="text-2xl font-black tracking-tight text-slate-900">
              {formatToman(listing.deposit_toman, { unit: true })}
            </p>
          </div>
        ) : (
          <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
            <div>
              <p className="text-xs font-semibold text-slate-600">ودیعه</p>
              <p className="text-xl font-black tracking-tight text-slate-900">{formatToman(listing.deposit_toman)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-600">اجارهٔ ماهانه</p>
              <p className="text-xl font-black tracking-tight text-slate-900">{formatToman(listing.rent_toman)}</p>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-xs text-slate-600">
          <Wallet size={13} className="text-slate-400" />
          هزینهٔ مؤثر ماهانه
          <b className="text-sm text-slate-900">{formatToman(listing.effective_monthly_cost)}</b>
        </span>
        {listing.can_convert ? (
          <Chip tone="green">
            <Handshake size={12} /> قابل تبدیل
          </Chip>
        ) : (
          <Chip>غیرقابل تبدیل</Chip>
        )}
      </div>
    </div>
  );
}

function LocationLine({ listing }: { listing: Listing }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-600">
      <MapPin size={14} className="text-slate-400" />
      <span className="font-medium text-slate-700">{listing.neighborhood}</span>
      {listing.district && <span className="text-slate-500">· {listing.district}</span>}
      {/* Some adverts blur the pin; saying so is more useful than a map marker
          that quietly claims more precision than we have. */}
      {listing.location_precision === "FUZZY" && <Chip>موقعیت تقریبی</Chip>}
      {listing.location_precision === "NEIGHBORHOOD" && <Chip>فقط در حد محله</Chip>}
    </p>
  );
}

/** Keep this one, and send it to someone.
 *
 * A property page with nothing to *do* on it is a dead end -- the two things
 * a renter reaches for while comparing flats are a shortlist and a link they
 * can paste into a chat. The shortlist is this browser's (localStorage): no
 * account exists to hang it on yet, and a saved flat is worth more surviving
 * a refresh than nothing surviving at all. */
function ListingActions({ listing }: { listing: Listing }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const storageKey = "maskan:saved-listings";

  useEffect(() => {
    try {
      const saved: string[] = JSON.parse(window.localStorage.getItem(storageKey) ?? "[]");
      setSaved(saved.includes(listing.id));
    } catch {
      // A blocked or corrupted store is not worth an error state; the button
      // simply starts unpressed.
    }
  }, [listing.id]);

  const toggleSaved = useCallback(() => {
    setSaved((wasSaved) => {
      const next = !wasSaved;
      try {
        const list: string[] = JSON.parse(window.localStorage.getItem(storageKey) ?? "[]");
        const without = list.filter((id) => id !== listing.id);
        window.localStorage.setItem(storageKey, JSON.stringify(next ? [...without, listing.id] : without));
      } catch {
        // Ignored on purpose -- see above.
      }
      return next;
    });
  }, [listing.id]);

  const share = useCallback(async () => {
    const url = `${window.location.origin}/listing/${encodeURIComponent(listing.id)}`;
    // The native sheet on a phone, the clipboard on a desktop. Both end with
    // the same confirmation, because a copy with no feedback reads as a
    // button that did nothing.
    try {
      if (navigator.share) await navigator.share({ title: listing.title, url });
      else await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // A dismissed share sheet is not a failure.
    }
  }, [listing.id, listing.title]);

  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={toggleSaved}
        aria-pressed={saved}
        className={clsx(
          "flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-semibold transition",
          saved
            ? "border-brand bg-brand-light text-brand"
            : "border-line bg-white text-slate-700 hover:border-line-strong hover:bg-slate-50",
        )}
      >
        <Bookmark size={16} className={saved ? "fill-brand" : undefined} />
        {saved ? "ذخیره شد" : "ذخیرهٔ ملک"}
      </button>
      <button
        type="button"
        onClick={share}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-line bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-line-strong hover:bg-slate-50"
      >
        {copied ? <CheckCircle2 size={16} className="text-brand" /> : <Share2 size={16} />}
        {copied ? "لینک کپی شد" : "اشتراک‌گذاری"}
      </button>
    </div>
  );
}

/** How much of an advert is shown before it is folded away, in pixels. */
const MAX_DESCRIPTION_HEIGHT = 280;

/** The advert's own prose, folded at a readable height.
 *
 * Two things were making this the worst-looking block on the page. Sellers
 * separate every bullet with three or four blank lines, which `pre-line`
 * faithfully reproduced as columns of nothing; and an unfolded advert -- these
 * run to several screens of bullet lists and phone-number pleas -- buried the
 * sections underneath it. So the blank runs are collapsed to one, and anything
 * still taller than a comfortable read is folded behind a fade. Short
 * descriptions are not folded at all, so the control only appears when there
 * is something behind it. */
function Description({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const tidied = useMemo(() => text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim(), [text]);

  // Measured rather than guessed from the character count: a length threshold
  // folded adverts that fitted anyway, leaving the fold's own reserved height
  // as a band of white under the last line.
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    setOverflows(node.scrollHeight > MAX_DESCRIPTION_HEIGHT + 24);
  }, [tidied]);

  const folded = overflows && !expanded;

  return (
    <div>
      <div
        ref={box}
        className="relative overflow-hidden transition-[max-height] duration-300"
        style={{ maxHeight: folded ? MAX_DESCRIPTION_HEIGHT : undefined }}
      >
        <p className="max-w-[70ch] whitespace-pre-line text-sm leading-7 text-slate-700">{tidied}</p>
        {folded && (
          // A hard cut mid-sentence reads as a rendering bug; the fade says
          // "there is more" without a second label to explain it.
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-white to-transparent" />
        )}
      </div>
      {overflows && (
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          className="mt-2 flex items-center gap-1 text-sm font-semibold text-brand transition hover:opacity-75"
        >
          <ChevronDown size={15} className={clsx("transition-transform", expanded && "rotate-180")} />
          {expanded ? "بستن متن آگهی" : "نمایش کامل متن آگهی"}
        </button>
      )}
    </div>
  );
}

export function ListingDetail({ listing, variant = "modal" }: { listing: Listing; variant?: DetailVariant }) {
  const images = listing.images ?? [];
  const provenance = listing.provenance;
  const isPage = variant === "page";

  /** Whether the overlay's title bar has left its place in the flow and is
   * riding the top of the dialog.
   *
   * A sticky element cannot ask this of CSS, so a zero-height sentinel is put
   * where the bar sits when the reader is at the top and watched against the
   * line the bar sticks to (top-14 = 56px). Once it scrolls past, the bar is
   * stuck, and it is only *then* that it should look like a floating card --
   * at rest it is simply the head of the article. */
  const stickySentinel = useRef<HTMLDivElement>(null);
  const [isStuck, setIsStuck] = useState(false);
  useEffect(() => {
    const node = stickySentinel.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      // Below the fold is also "not intersecting", so the side matters: only a
      // sentinel that has gone *up* past the line means the bar is stuck.
      ([entry]) => setIsStuck(!entry.isIntersecting && entry.boundingClientRect.top < 57),
      { rootMargin: "-57px 0px 0px 0px", threshold: 1 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // The four amenities every renter filters on are reported either way --
  // "پارکینگ ندارد" is as much a decision as "پارکینگ دارد", and a list that
  // only ever prints what is present leaves the reader unable to tell a
  // missing feature from an unfilled field. The rest are bonuses: they are
  // listed when present and simply absent otherwise.
  const coreAmenities: { label: string; has: boolean }[] = [
    { label: "آسانسور", has: listing.has_elevator },
    { label: "پارکینگ", has: listing.has_parking },
    { label: "انباری", has: listing.has_storage },
    { label: "بالکن", has: listing.has_balcony },
  ];
  const extraAmenities = [
    listing.is_renovated && "بازسازی‌شده",
    listing.is_furnished && "مبله",
    listing.has_pool && "استخر",
    listing.has_sauna && "سونا",
    listing.has_jacuzzi && "جکوزی",
  ].filter(Boolean) as string[];

  /** Whatever the advert carried that the normalised sections above do not. */
  const extraAttributes = useMemo(
    () =>
      Object.entries(listing.attributes ?? {}).filter(
        ([key]) => !ALREADY_SHOWN.has(key.replace(/[‌\s]/g, "")),
      ),
    [listing.attributes],
  );

  /** Every measurable fact about the unit, as one ruled grid.
   *
   * These were four tiles above the fold plus three more buried inside the
   * location section, which is why the same reader had to hunt for طبقه in one
   * place and جهت ساختمان in another. */
  const specs = [
    { icon: Ruler, label: "متراژ", value: `${fa(listing.area_sqm)} متر`, field: "area_sqm" },
    { icon: Home, label: "اتاق", value: fa(listing.rooms), field: "rooms" },
    {
      icon: Building2,
      label: "طبقه",
      value: FLOOR_LABEL(listing.floor, listing.total_floors),
      field: "total_floors",
    },
    { icon: Sparkles, label: "سال ساخت", value: listing.build_year ? faYear(listing.build_year) : "—" },
    { icon: TrainFront, label: "نزدیک‌ترین ایستگاه", value: listing.nearest_metro_name },
    { icon: Footprints, label: "پیاده تا مترو", value: faMinutes(listing.metro_walk_mins) },
    ...(listing.direction ? [{ icon: Compass, label: "جهت ساختمان", value: listing.direction }] : []),
    ...(listing.kitchen_type ? [{ icon: Sofa, label: "آشپزخانه", value: listing.kitchen_type }] : []),
    ...(listing.units_per_floor != null
      ? [{ icon: Layers, label: "واحد در طبقه", value: fa(listing.units_per_floor) }]
      : []),
    ...(listing.min_contract_months != null
      ? [{ icon: Clock3, label: "حداقل قرارداد", value: `${fa(listing.min_contract_months)} ماه` }]
      : []),
  ];

  /** Everything below the price and the headline. Identical in both variants
   * -- they differ in the layout around this, not in the content. */
  const body = (
    <div className="space-y-4">
      <Card icon={ListTree} title="مشخصات و امکانات" bodyClassName="">
        <div
          className={clsx(
            "grid divide-y divide-line-soft [&>*]:border-line-soft",
            // Ruled cells: on a wide column the vertical rule between the two
            // halves is what keeps a row reading as a row.
            "sm:grid-cols-2 sm:divide-y-0 sm:[&>*:nth-child(n+3)]:border-t sm:[&>*:nth-child(even)]:border-s",
          )}
        >
          {specs.map((spec) => (
            <Spec
              key={spec.label}
              icon={spec.icon}
              label={spec.label}
              value={spec.value}
              mark={spec.field ? <DerivedMark provenance={provenance} field={spec.field} /> : undefined}
            />
          ))}
        </div>

        {/* Amenities live in the same card rather than one of their own: on
            their own, four chips occupied a full-width panel that was ninety
            percent empty. */}
        <div className="border-t border-line-soft bg-slate-50/60 p-4">
          <div className="flex flex-wrap gap-2">
            {coreAmenities.map(({ label, has }) => (
              <Chip key={label} tone={has ? "green" : "muted"}>
                {has ? <Check size={12} /> : <Minus size={12} />}
                {label}
              </Chip>
            ))}
            {extraAmenities.map((amenity) => (
              <Chip key={amenity} tone="green">
                <Check size={12} />
                {amenity}
              </Chip>
            ))}
            {listing.pets_policy && (
              <Chip tone={listing.pets_policy === "allowed" ? "green" : "slate"}>
                <PawPrint size={12} /> حیوان خانگی: {PETS_LABEL[listing.pets_policy]}
              </Chip>
            )}
            {(listing.suitable_for ?? []).map((who) => (
              <Chip key={who} tone="blue">
                <Users size={12} /> {who}
              </Chip>
            ))}
          </div>

          {FEATURE_GROUPS.some((group) => (listing.features?.[group.key]?.length ?? 0) > 0) && (
            <div className="mt-3 grid gap-x-8 gap-y-1.5 border-t border-line-soft pt-3 sm:grid-cols-2">
              {FEATURE_GROUPS.map((group) => {
                const values = listing.features?.[group.key];
                if (!values?.length) return null;
                return (
                  <div key={group.key} className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="flex items-center gap-1.5 text-slate-500">
                      <group.icon size={13} className="text-slate-400" />
                      {group.label}
                    </span>
                    <span className="text-end font-semibold text-slate-800">{values.join("، ")}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {listing.description && (
        <Card icon={Text} title="توضیحات آگهی‌دهنده">
          <Description text={listing.description} />
        </Card>
      )}

      {(listing.in_tarh_terafik || listing.in_tarh_aloodegi) && (
        <Card icon={MapPin} title="محدودهٔ ترافیکی">
          <div className="flex flex-wrap gap-2">
            {listing.in_tarh_terafik && <Chip tone="amber">داخل طرح ترافیک</Chip>}
            {listing.in_tarh_aloodegi && <Chip tone="amber">داخل طرح کنترل آلودگی هوا</Chip>}
          </div>
        </Card>
      )}

      {/* The advertiser's own specification table, verbatim underneath our
          normalised view: anything we failed to model is still visible. It is
          *extra* -- whatever the ad carried beyond the fields above -- not a
          fuller version of them, so it is not billed as "مشخصات کامل". */}
      {extraAttributes.length > 0 && (
        <Card
          icon={ListTree}
          title="سایر مشخصات آگهی"
          bodyClassName="grid sm:grid-cols-2"
        >
          {extraAttributes.map(([key, value], row) => (
            <div
              key={key}
              className={clsx(
                "flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm",
                // Zebra by visual row rather than by index: with two columns
                // the odd/even of the array stripes vertically, not across.
                Math.floor(row / 2) % 2 === 1 && "bg-slate-50/70",
                row % 2 === 1 && "sm:border-s sm:border-line-soft",
              )}
            >
              <dt className="shrink-0 text-slate-500">{key}</dt>
              <dd className="text-end font-semibold text-slate-800">{faDigits(value)}</dd>
            </div>
          ))}
        </Card>
      )}

      {/* Development aid only: a way to check our extraction against the
          original advert. It comes out before launch -- the marketplace we
          sourced from is not part of this product. */}
      {listing.source_url && (
        <a
          href={listing.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 transition hover:text-slate-600"
        >
          <ExternalLink size={12} />
          آگهی مبدأ (فقط برای بررسی داده)
        </a>
      )}
    </div>
  );

  /** The one-line status of the offer, repeated at the top of both variants:
   * how the deal is structured and anything about it that changes what the
   * renter has to plan for. */
  const headlineChips = (
    <div className="flex flex-wrap items-center gap-2">
      <Chip tone={listing.is_full_rahn ? "green" : "slate"}>{listing.is_full_rahn ? "رهن کامل" : "رهن و اجاره"}</Chip>
      {listing.can_convert && (
        <Chip tone="green">
          <Handshake size={12} /> قابل تبدیل
        </Chip>
      )}
      <Chip tone="blue">
        <Footprints size={12} />
        {faMinutes(listing.metro_walk_mins)} تا مترو
      </Chip>
      {listing.in_tarh_terafik && <Chip tone="amber">طرح ترافیک</Chip>}
    </div>
  );

  if (isPage) {
    return (
      <article className="space-y-5">
        <ListingGallery
          images={images}
          title={listing.title}
          authentic={listing.images_are_authentic !== false}
          variant="page"
        />

        {/* Full width, above both columns. On a phone the grid collapses to a
            single column in source order, so with the title inside the content
            column the price card landed *below* the whole advert -- several
            screens past the point where a renter decides. Lifting the title
            out puts the price second on a phone and costs the desktop nothing:
            a headline spanning both columns is where a headline belongs. */}
        <header className="space-y-2.5 rounded-2xl border border-line bg-white p-5">
          <h1 className="text-2xl font-black leading-9 tracking-tight text-slate-900 sm:text-3xl">{listing.title}</h1>
          <LocationLine listing={listing} />
          {headlineChips}
        </header>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_336px] lg:items-start">
          <div className="order-last space-y-4 lg:order-none">{body}</div>

          {/* On a page this long the price has to follow the reader rather
              than scroll away with the first screen. */}
          <aside className="space-y-3 lg:sticky lg:top-20">
            <PriceCard listing={listing} />
            <ListingActions listing={listing} />

            <div className="overflow-hidden rounded-2xl border border-line bg-white">
              <div className="h-56">
                <ListingLocationMap listing={listing} />
              </div>
              <p className="flex items-start gap-1.5 border-t border-line-soft px-3.5 py-2.5 text-xs text-slate-600">
                <MapPin size={13} className="mt-1 shrink-0 text-slate-400" />
                {listing.location_precision && listing.location_precision !== "EXACT"
                  ? "محدودهٔ تقریبی ملک — آگهی‌دهنده موقعیت دقیق را منتشر نکرده است."
                  : `${listing.neighborhood}${listing.district ? ` · ${listing.district}` : ""}`}
              </p>
            </div>
            {listing.published_text && (
              <p className="whitespace-pre-line px-1 text-xs leading-6 text-slate-500">{faDigits(listing.published_text)}</p>
            )}
          </aside>
        </div>
      </article>
    );
  }

  return (
    <article className="space-y-4">
      <ListingGallery images={images} title={listing.title} authentic={listing.images_are_authentic !== false} />

      {/* Which property this is, kept on screen for the whole scroll.
          The overlay is long -- gallery, price, four sections, the ad's own
          table -- and without this the reader loses the title and the figure
          they are comparing against as soon as they scroll past the fold. It
          is offset below the floating toolbar (see ListingModal) so the two
          pieces of chrome sit in a column instead of on top of each other.

          Two looks, one element. At rest it is the head of the article: full
          width to the dialog's edges, a hairline under it, nothing else. Once
          it detaches and starts floating over the content it becomes a card --
          inset from the sides, rounded, lifted on a shadow -- because that is
          what says "this is on top of what you are reading" rather than "this
          is part of it". The border is always there, transparent on the sides
          until it is needed, so nothing shifts by a pixel as the two states
          cross-fade. */}
      <div ref={stickySentinel} aria-hidden className="h-px" />
      <div
        className={clsx(
          "sticky top-14 z-[5] border border-transparent bg-white/95 px-4 py-2.5 backdrop-blur transition-all duration-300 ease-out sm:px-6",
          isStuck
            ? "mx-0 rounded-2xl border-line shadow-lg shadow-slate-900/10"
            : "-mx-4 border-b-line sm:-mx-6",
        )}
      >
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="truncate text-base font-bold leading-7 text-slate-900">{listing.title}</h2>
          <span className="shrink-0 text-xs text-slate-500">
            ماهانهٔ مؤثر <b className="text-slate-800">{formatToman(listing.effective_monthly_cost)}</b>
          </span>
        </div>
        <LocationLine listing={listing} />
      </div>

      {headlineChips}
      <PriceCard listing={listing} />
      <ListingActions listing={listing} />
      {body}

      {listing.published_text && (
        <p className="whitespace-pre-line text-xs leading-6 text-slate-500">{faDigits(listing.published_text)}</p>
      )}
    </article>
  );
}

/** Fetches the listing by id and renders it, with Persian loading and failure
 * states -- both routes that show a listing (the page and the modal) use this
 * so the two can never drift apart. */
export default function ListingDetailLoader({ id, variant = "modal" }: { id: string; variant?: DetailVariant }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setListing(null);
    setError(null);
    getListing(id)
      .then((result) => active && setListing(result))
      .catch((cause: Error) => active && setError(cause.message || "این آگهی در دسترس نیست."));
    return () => {
      active = false;
    };
  }, [id]);

  if (error) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-6 text-center text-sm text-rose-700">
        {error}
        <p className="mt-1 text-xs text-rose-600">
          ممکن است این آگهی حذف شده باشد. به فهرست برگردید و مورد دیگری را انتخاب کنید.
        </p>
      </div>
    );
  }

  if (!listing) {
    return (
      <div className="space-y-4" aria-busy>
        <div
          className={clsx(
            "w-full animate-pulse rounded-2xl bg-slate-200/70",
            variant === "page" ? "aspect-[16/9]" : "aspect-[4/3]",
          )}
        />
        <div className="h-5 w-2/3 animate-pulse rounded bg-slate-200/70" />
        <div className="h-20 w-full animate-pulse rounded-2xl bg-slate-200/70" />
      </div>
    );
  }

  return <ListingDetail listing={listing} variant={variant} />;
}
