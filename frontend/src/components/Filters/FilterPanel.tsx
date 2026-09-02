"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowUpDown,
  BedSingle,
  BedDouble,
  Briefcase,
  Building2,
  Bus,
  Car,
  ChevronDown,
  Crosshair,
  Footprints,
  Handshake,
  Image as ImageIcon,
  Info,
  MapPin,
  Package,
  RotateCcw,
  Ruler,
  Scan,
  Search,
  Sparkles,
  Train,
  Wallet,
  X,
} from "lucide-react";

import clsx from "clsx";

import { searchTehranAddresses, type AddressCandidate } from "@/lib/api";
import { useSearchStore } from "@/store/useSearchStore";
import type { CommuteMode, FinancialPersona, LivingKind, WeightedCriterion, WeightLevel } from "@/types";
import NeighborhoodPicker from "./NeighborhoodPicker";

const LIVING_KINDS: { key: LivingKind; label: string; hint: string }[] = [
  { key: "standard", label: "ملک مستقل", hint: "آپارتمان یا خانه‌ی کامل" },
  { key: "shared", label: "هم‌خانه و خوابگاه", hint: "اتاق، تخت، سکونت مشترک یا پارکینگ" },
];

const MAX_ROOMS = 5;
const MILLION = 1_000_000;
// Current Iranian year -- the سال ساخت presets are phrased as ages and
// converted to a year floor, which is what the backend filters on.
const CURRENT_JALALI_YEAR = 1405;
const BUILD_AGE_PRESETS = [
  { label: "هر سالی", maxAge: null },
  { label: "نوساز", maxAge: 5 },
  { label: "زیر ۱۰ سال", maxAge: 10 },
  { label: "زیر ۲۰ سال", maxAge: 20 },
] as const;

function millionsToToman(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.round(n * MILLION) : 0;
}

function tomanToMillionsInputValue(value: number): string {
  return value > 0 ? String(value / MILLION) : "";
}

function positiveOrZero(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
}

const COMMUTE_MODES: { value: CommuteMode; label: string; Icon: typeof Footprints }[] = [
  { value: "walk", label: "پیاده", Icon: Footprints },
  { value: "transit", label: "مترو/اتوبوس", Icon: Bus },
  { value: "drive", label: "خودرو", Icon: Car },
];

const AMENITIES = [
  { key: "hasElevator", label: "آسانسور", Icon: ArrowUpDown },
  { key: "hasParking", label: "پارکینگ", Icon: Car },
  { key: "hasStorage", label: "انباری", Icon: Package },
  { key: "hasBalcony", label: "بالکن", Icon: Building2 },
  { key: "hasImages", label: "عکس‌دار", Icon: ImageIcon },
] as const;

/** Deal shape: whether the price is fixed as رهن کامل, negotiable as قابل
 * تبدیل, or unconstrained. It is not an amenity -- it changes what the price
 * *means*, not what the flat contains -- and the three states are exclusive,
 * so this is a choice of one, not a pair of independent switches: a listing
 * cannot be رهن کامل and still have rent left to convert. */
const DEAL_SHAPES = [
  { key: "fullRahnOnly", label: "رهن کامل", Icon: Wallet },
  { key: "convertibleOnly", label: "قابل تبدیل", Icon: Handshake },
] as const;

type DealShapeKey = (typeof DEAL_SHAPES)[number]["key"];

/** Where a تبدیل should land for a convertible listing. The engine moves the
 * deposit/rent split along the conversion line, which leaves the total cost
 * identical and only changes which listings the user can actually afford. */
const FINANCIAL_PERSONAS: { value: FinancialPersona; label: string; hint: string }[] = [
  { value: "prefer_higher_rent", label: "ودیعه کمتر", hint: "اجاره ماهانه بیشتر" },
  { value: "balanced", label: "همانی که هست", hint: "بدون تبدیل" },
  { value: "prefer_higher_deposit", label: "اجاره کمتر", hint: "ودیعه بیشتر" },
];

/** Every numeric field in the panel.
 *
 * `placeholder:text-slate-500` matters more here than it looks: از/تا are not
 * decoration, they are the only labels these fields have (see RangeInputs), and
 * at the browser default placeholder grey they were the faintest text on a
 * panel of otherwise solid type. `tabular-nums` keeps a figure from reflowing
 * as it is typed. */
const inputClass =
  "w-full rounded-xl border border-line bg-white px-3 py-2 text-sm tabular-nums text-slate-900 outline-none transition " +
  "placeholder:text-slate-500 hover:border-line-strong focus:border-brand focus:ring-2 focus:ring-brand/20";

/** Section shell: one heading, one rule, consistent spacing. Keeping this in
 * one place is what stops the panel from drifting into six slightly different
 * card styles as filters get added. */
const WEIGHT_LEVELS: { value: WeightLevel; label: string }[] = [
  { value: "low", label: "کم" },
  { value: "normal", label: "متوسط" },
  { value: "high", label: "زیاد" },
];

/** How much a criterion counts in the ranking, in three steps.
 *
 * Three steps and not a slider on purpose: the scores behind these weights are
 * estimates, so offering 100 positions would promise a precision the ranking
 * does not have -- and "کم / متوسط / زیاد" is a judgement a person can
 * actually make about their own priorities. It sits in the section heading
 * because it belongs to that criterion, and it never removes a listing: it
 * only reorders the ones the filters already kept. */
function WeightPicker({ value, onChange }: { value: WeightLevel; onChange: (level: WeightLevel) => void }) {
  return (
    <div
      role="group"
      aria-label="اهمیت در رتبه‌بندی"
      title="اهمیت این معیار در رتبه‌بندی نتایج"
      className="flex shrink-0 overflow-hidden rounded-lg border border-line bg-slate-50"
    >
      {WEIGHT_LEVELS.map(({ value: level, label }) => (
        <button
          key={level}
          type="button"
          aria-pressed={value === level}
          onClick={() => onChange(level)}
          className={clsx(
            "px-2.5 py-1.5 text-xs font-medium transition-colors",
            value === level ? "bg-brand text-white" : "text-slate-500 hover:bg-slate-100",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The paragraph behind a question mark.
 *
 * Several controls here need a sentence of explanation -- why the search area
 * has no weight, what کیفیت محله is computed from, why nothing is dropped for
 * being far from a metro -- and printing all of them left the panel reading as
 * an essay with form fields in it, three lines of grey prose for every row of
 * controls. The explanation is worth keeping and worth not showing by default:
 * this is the standard "i" affordance, closed until asked. */
function Explainer({ children, label = "توضیح این بخش" }: { children: React.ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="-mt-1">
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        aria-expanded={open}
        className={clsx(
          "flex items-center gap-1 text-xs font-medium transition-colors",
          open ? "text-brand" : "text-slate-500 hover:text-slate-700",
        )}
      >
        <Info size={13} />
        {label}
      </button>
      {open && (
        <p className="mt-1.5 rounded-xl border border-line-soft bg-slate-50 px-3 py-2 text-xs leading-6 text-slate-600">
          {children}
        </p>
      )}
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  hint,
  weight,
  weightLabel = "اهمیت در رتبه‌بندی",
  children,
}: {
  icon: typeof Wallet;
  title: string;
  hint?: string;
  weight?: { value: WeightLevel; onChange: (level: WeightLevel) => void };
  /** What this dial actually weighs, when the section's own title does not say
   * it. A section is a place to *filter*; the weight beside it belongs to a
   * ranking criterion, and where the two are not the same thing (the search
   * area is a filter, but the dial next to it weighs کیفیت محله) leaving it
   * unnamed makes the dial unreadable. */
  weightLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="min-w-0 border-b border-line-soft pb-5 last:border-b-0">
      <div className="mb-3 space-y-2">
        <div className="flex items-baseline gap-1.5">
          <Icon size={15} className="shrink-0 translate-y-0.5 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
          {hint && <span className="text-xs text-slate-500">{hint}</span>}
        </div>
        {/* The importance dial gets its own line and its own word. Sharing the
            heading's line wrapped the title in this column's width, and left
            three unexplained buttons floating beside it -- a control nobody
            reads as "how much this counts" unless it says so. */}
        {weight && (
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-500">{weightLabel}</span>
            <WeightPicker value={weight.value} onChange={weight.onChange} />
          </div>
        )}
      </div>
      {children}
    </section>
  );
}

/** A band of related sections under one heading.
 *
 * The panel had grown to eleven sections in one flat column, which made two
 * different things look alike: "where" and "how much" are the two questions a
 * renter actually starts from, and everything else is refinement. Grouping
 * them also gives a weight somewhere honest to live -- the money weight
 * belongs to the *pair* of ودیعه and اجاره, not to either one of them, and
 * hanging it off the ودیعه heading said the opposite. */
function Group({
  title,
  hint,
  weight,
  summary,
  children,
}: {
  title: string;
  hint?: string;
  weight?: { value: WeightLevel; onChange: (level: WeightLevel) => void };
  /** What this group currently narrows the search to, in a few words.
   *
   * A collapsed group must still answer "did I set anything in there?" -- a
   * folded band that only says «هزینه» turns the panel into a memory test. */
  summary?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-slate-50/60 p-2.5">
      <header className="mb-2 flex items-center justify-between gap-2 px-1.5 pt-1">
        {/* The heading is the fold control. The panel is three screens tall,
            so a reader who has settled «کجا» wants it out of the way to reach
            «ویژگی‌های ملک» -- and the summary means folding it never hides
            what it is doing. */}
        <button
          type="button"
          onClick={() => setOpen((wasOpen) => !wasOpen)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-start"
        >
          <ChevronDown
            size={15}
            className={clsx("shrink-0 text-slate-500 transition-transform", !open && "-rotate-90")}
          />
          <h2 className="flex min-w-0 items-baseline gap-2 text-sm font-bold text-slate-800">
            {title}
            {!open && summary && <span className="truncate text-xs font-medium text-slate-500">{summary}</span>}
          </h2>
        </button>
        {weight && open && (
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-xs text-slate-500">اهمیت</span>
            <WeightPicker value={weight.value} onChange={weight.onChange} />
          </div>
        )}
      </header>
      {open && (
        <>
          {hint && (
            <div className="mb-2 px-1.5">
              <Explainer label="این وزن روی چه چیزی اثر می‌گذارد؟">{hint}</Explainer>
            </div>
          )}
          <div className="flex min-w-0 flex-col gap-5 rounded-xl bg-white p-3.5 ring-1 ring-line">{children}</div>
        </>
      )}
    </section>
  );
}


/** از / تا pair, the shape every numeric filter here takes -- matching how
 * Iranian listing sites ask for a range.
 *
 * The two words label the fields from *inside* them, as placeholder text,
 * rather than from a row of captions above. Stacked captions doubled the
 * height of every numeric filter in a column that already scrolls, and at
 * this width they drifted out of line with the boxes they belonged to. A
 * field the user has typed in no longer needs to be told what it is. */
function RangeInputs({
  fromValue,
  toValue,
  onFromChange,
  onToChange,
  fromLabel = "از",
  toLabel = "تا",
  toPlaceholder,
}: {
  fromValue: string;
  toValue: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  fromLabel?: string;
  toLabel?: string;
  toPlaceholder?: string;
}) {
  /** The word stays put once a figure is typed into the box.
   *
   * از/تا were placeholders, so the moment a user filled the first field the
   * only thing distinguishing the two boxes disappeared -- and on a range
   * filter, "which one is the ceiling?" is the entire question. */
  const field = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    placeholder?: string,
  ) => (
    <div className="relative flex-1">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 start-3 flex items-center text-xs font-medium text-slate-500"
      >
        {label}
      </span>
      <input
        type="number"
        min={0}
        aria-label={label}
        placeholder={placeholder ?? ""}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${inputClass} ps-9`}
      />
    </div>
  );

  return (
    <div className="flex items-center gap-2">
      {field(fromLabel, fromValue, onFromChange)}
      <span aria-hidden className="shrink-0 text-slate-400">—</span>
      {field(toLabel, toValue, onToChange, toPlaceholder === toLabel ? undefined : toPlaceholder)}
    </div>
  );
}

/** The one pill shape every toggle in this panel uses. */
function Pill({
  active,
  onClick,
  disabled = false,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      // whitespace-nowrap: at 360px these sit three to a row, and "قابل تبدیل"
      // was breaking across two lines while "رهن کامل" beside it stayed on one,
      // so a row of equal choices rendered at unequal heights.
      className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-2 text-xs font-medium transition-colors ${
        active
          ? "border-brand bg-brand text-white"
          : disabled
            ? "cursor-not-allowed border-line-soft bg-slate-50 text-slate-400"
            : "border-line text-slate-700 hover:border-brand hover:bg-brand-light/40 hover:text-brand"
      }`}
    >
      {children}
    </button>
  );
}

export default function FilterPanel() {
  const {
    livingKind,
    minDepositToman,
    depositToman,
    minRentToman,
    rentToman,
    minAreaSqm,
    maxAreaSqm,
    hasElevator,
    hasParking,
    hasBalcony,
    hasStorage,
    hasImages,
    fullRahnOnly,
    convertibleOnly,
    minBuildYear,
    minFloor,
    maxFloor,
    financialPersona,
    rooms,
    selectedNeighborhoods,
    searchInViewport,
    workplaceLocation,
    commuteImportance,
    commuteMode,
    criteriaWeights,
    isPickingWorkplace,
    setFilters,
    runSearch,
    resetFilters,
    totalCount,
    isLoading,
  } = useSearchStore();

  /** One criterion's weight, changed without disturbing the others. */
  const weightSlot = (criterion: WeightedCriterion) => ({
    value: criteriaWeights[criterion],
    onChange: (level: WeightLevel) => setFilters({ criteriaWeights: { ...criteriaWeights, [criterion]: level } }),
  });

  // The workplace dial is continuous on the wire (0..1) but is offered in the
  // same three steps as every other criterion, so the panel reads as one
  // control repeated rather than a slider here and pills everywhere else.
  const commuteLevel: WeightLevel = commuteImportance < 0.35 ? "low" : commuteImportance < 0.7 ? "normal" : "high";
  const setCommuteLevel = (level: WeightLevel) =>
    setFilters({ commuteImportance: level === "low" ? 0.2 : level === "normal" ? 0.5 : 0.9 });

  const [addressQuery, setAddressQuery] = useState("");
  const [isGeocoding, setIsGeocoding] = useState(false);
  const [geocodeError, setGeocodeError] = useState<string | null>(null);
  /** The candidates the last address search returned, for the user to pick
   * from. Emptied once one is chosen, so the list is only ever open while
   * there is an unanswered question on screen. */
  const [addressResults, setAddressResults] = useState<AddressCandidate[]>([]);

  // Filter changes update the shared search context and debounce-trigger a
  // re-search (docs/FRONTEND_STATE.md SS2, "filters -> search context"
  // direction of the bidirectional sync).
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  // Mounting is not a filter change. This panel is unmounted while the user
  // is in the chat and mounted again when they come back, and searching on
  // arrival threw away the list they were already reading -- sending the feed
  // to the top and the map home -- to fetch the same results a second time.
  // The session's first search is issued once by the page (app/page.tsx).
  const filtersTouched = useRef(false);
  useEffect(() => {
    if (!filtersTouched.current) {
      filtersTouched.current = true;
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSearch();
    }, 300);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    livingKind,
    minDepositToman,
    depositToman,
    minRentToman,
    rentToman,
    minAreaSqm,
    maxAreaSqm,
    hasElevator,
    hasParking,
    hasBalcony,
    hasStorage,
    hasImages,
    fullRahnOnly,
    convertibleOnly,
    minBuildYear,
    minFloor,
    maxFloor,
    financialPersona,
    rooms,
    selectedNeighborhoods,
    workplaceLocation,
    commuteImportance,
    commuteMode,
    criteriaWeights,
    // searchInViewport is deliberately absent: switching it on hands the
    // search to the map (which alone knows the rectangle), and switching it
    // off runs one from the toggle itself. Listing it here would fire a
    // second, duplicate request on every flip.
  ]);

  const handleGeocodeSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = addressQuery.trim();
    if (!query || isGeocoding) return;
    setIsGeocoding(true);
    setGeocodeError(null);
    setAddressResults([]);
    try {
      const results = await searchTehranAddresses(query);
      if (results.length === 0) {
        setGeocodeError("آدرسی پیدا نشد. روی نقشه هم می‌توانید محل کار را انتخاب کنید.");
        return;
      }
      // Even a single hit is offered rather than applied: "پیدا شد" and "this
      // is the place I meant" are two different claims, and only the user can
      // make the second one.
      setAddressResults(results);
    } catch (error) {
      setGeocodeError(error instanceof Error ? error.message : "جستجوی آدرس با خطا مواجه شد.");
    } finally {
      setIsGeocoding(false);
    }
  };

  const chooseAddress = (candidate: AddressCandidate) => {
    setFilters({
      workplaceLocation: { lat: candidate.lat, lon: candidate.lon, name: candidate.label },
    });
    setAddressResults([]);
    setAddressQuery("");
  };

  const amenityState = { hasElevator, hasParking, hasBalcony, hasStorage, hasImages };
  const dealState = { fullRahnOnly, convertibleOnly };

  /** Selecting one deal shape clears the other, and selecting the one already
   * chosen clears it -- three states out of two flags, with the impossible
   * fourth (both at once) unreachable by construction rather than by a check
   * further down the stack. Choosing رهن کامل also drops the تبدیل preference
   * back to neutral, so a stale persona cannot travel with a search where
   * conversion is meaningless. */
  const selectDealShape = (choice: DealShapeKey | null) => () => {
    const next = choice !== null && dealState[choice] ? null : choice;
    setFilters({
      fullRahnOnly: next === "fullRahnOnly",
      convertibleOnly: next === "convertibleOnly",
      ...(next === "fullRahnOnly" ? { financialPersona: "balanced" as FinancialPersona } : {}),
    });
  };

  /** "Search what I can see" and "search these محله‌ها" are two answers to the
   * same question, so choosing one puts the other away. Turning it *on* leaves
   * the search to the map, which is the only thing that knows the rectangle
   * being searched; turning it off re-runs here, since the map has nothing to
   * report once it is no longer the search area. */
  const toggleViewportSearch = () => {
    const next = !searchInViewport;
    setFilters({
      searchInViewport: next,
      isPickingNeighborhood: false,
      selectedListingId: null,
      restoreBounds: null,
    });
    if (!next) void runSearch();
  };

  /** How many filters are actually narrowing the search.
   *
   * The panel is eleven sections tall, so by the time a search returns nothing
   * the reason is usually three screens above the fold. A count -- and one
   * button that undoes all of it -- is the difference between "this site has
   * no flats in نارمک" and "I asked for four things at once". */
  const activeFilterCount = [
    minDepositToman > 0,
    depositToman > 0,
    minRentToman > 0,
    rentToman > 0,
    minAreaSqm > 0,
    maxAreaSqm > 0,
    rooms > 0,
    minFloor !== null,
    maxFloor !== null,
    minBuildYear > 0,
    hasElevator,
    hasParking,
    hasStorage,
    hasBalcony,
    hasImages,
    fullRahnOnly,
    convertibleOnly,
    livingKind !== "standard",
    financialPersona !== "balanced",
    selectedNeighborhoods.length > 0,
    searchInViewport,
    workplaceLocation !== null,
  ].filter(Boolean).length;

  /** One line per group, for when it is folded away. Only what is set --
   * an empty string leaves the heading alone rather than printing «همه». */
  const millions = (toman: number) => (toman / MILLION).toLocaleString("fa-IR");
  const range = (from: number, to: number, unit: string) =>
    from || to ? `${from ? millions(from) : "۰"}–${to ? millions(to) : "∞"} ${unit}` : "";
  const whereSummary = searchInViewport
    ? "محدودهٔ نقشه"
    : selectedNeighborhoods.length > 0
      ? `${selectedNeighborhoods.length.toLocaleString("fa-IR")} محله`
      : workplaceLocation
        ? "نزدیک محل کار"
        : "کل تهران";
  const costSummary = [range(minDepositToman, depositToman, "م ودیعه"), range(minRentToman, rentToman, "م اجاره")]
    .filter(Boolean)
    .join(" · ");
  const featureSummary = [
    minAreaSqm || maxAreaSqm
      ? `${minAreaSqm || "۰"}–${maxAreaSqm || "∞"} متر`.replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)])
      : "",
    rooms > 0 ? `${rooms.toLocaleString("fa-IR")}+ خواب` : "",
    [hasElevator && "آسانسور", hasParking && "پارکینگ", hasStorage && "انباری", hasBalcony && "بالکن"]
      .filter(Boolean)
      .join("، "),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    // `w-full`: this panel is a flex *item* in the page's row, so without it
    // the column is sized by its content -- folding every group away shrank
    // the whole panel to the width of the longest collapsed heading, and the
    // white cards visibly narrowed under the user. The section beside it sets
    // the width; the panel fills it.
    <div className="flex h-full w-full min-h-0 min-w-0 flex-col">
      {/* `overflow-x-hidden` is load-bearing, not tidiness. `overflow-y-auto`
          alone makes the *other* axis scrollable too (a `visible` axis
          computes to `auto` beside a scrolling one), so a single child whose
          min-content width beat the column -- a nowrap chip, a long
          neighborhood name -- turned this into a horizontally scrollable box.
          In RTL the surplus hangs off the far edge, so every card in the panel
          drew a few pixels out of line with the padding on the near side and
          the whole column looked lopsided, differently so as sections were
          folded away and the widest child came and went. Pinned to one axis,
          the cards sit centred in the panel whatever is inside them. */}
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto overflow-x-hidden p-5">
      {/* First, because it decides which market everything below is filtering.
          Shared rooms and dormitory beds are quoted per person, so mixing them
          into whole-unit results made an ordinary flat look overpriced beside
          a bed. The two are mutually exclusive by construction -- there is no
          "both", because the prices are not comparable. */}
      <Section icon={BedSingle} title="نوع سکونت">
        {/* Sized to sit *under* the filters, not over them. These were two
            tall two-line blocks at the head of the panel, and being the first
            and biggest thing in it they read as the main question the user had
            come to answer -- which they are not: almost everyone wants the
            default. The choice still has to be visible and reversible, so it
            keeps its own row and its selected colour; the explanatory line is
            what goes, into the button's title. */}
        <div className="grid grid-cols-2 gap-1.5">
          {LIVING_KINDS.map(({ key, label, hint }) => (
            <button
              key={key}
              type="button"
              title={hint}
              onClick={() => setFilters({ livingKind: key })}
              className={clsx(
                "rounded-lg border px-2.5 py-1.5 text-center text-xs font-medium transition-colors",
                livingKind === key
                  ? "border-brand bg-brand text-white"
                  : "border-line bg-white text-slate-600 hover:bg-slate-50",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </Section>

      <Group title="کجا" summary={whereSummary}>
      <Section
        icon={MapPin}
        title="محدوده جستجو"
        hint={searchInViewport ? undefined : selectedNeighborhoods.length > 0 ? undefined : "کل تهران"}
        weight={weightSlot("quality")}
        weightLabel="اهمیت کیفیت محله"
      >
        <div className="flex flex-col gap-3">
          {/* Where to search is a hard filter; the dial above is a separate
              thing -- the کیفیت محله criterion -- and it was sitting here
              unlabelled, which read as "how much the search area matters".
              Naming it is not enough on its own: کیفیت محله is a computed
              index, so one line says what it is computed from. */}
          <Explainer label="این وزن چه چیزی را می‌سنجد؟">
            محدودهٔ جستجو یک فیلتر است و وزن ندارد؛ وزن بالا برای «کیفیت محله» است — شاخصی از سطح قیمت و نوسازی
            بافت هر محله که تعیین می‌کند بین دو ملک مشابه، کدام محله مطلوب‌تر است.
          </Explainer>
          <button
            type="button"
            onClick={toggleViewportSearch}
            className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-xs font-medium transition-colors ${
              searchInViewport
                ? "border-brand bg-brand text-white"
                : "border-line text-slate-600 hover:border-brand"
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Scan size={14} />
              جستجو در محدوده نقشه
            </span>
            <span
              className={`flex h-4 w-7 shrink-0 items-center rounded-full p-0.5 transition-colors ${
                searchInViewport ? "bg-white/35" : "bg-slate-200"
              }`}
            >
              <span
                className={`h-3 w-3 rounded-full bg-white shadow transition-transform ${
                  searchInViewport ? "-translate-x-3" : "translate-x-0"
                }`}
              />
            </span>
          </button>

          {searchInViewport ? (
            <p className="text-xs leading-5 text-slate-500">
              همان بخشی از نقشه که می‌بینید جستجو می‌شود؛ با جابه‌جایی یا زوم، نتایج به‌روز می‌شوند. برای انتخاب محله،
              این حالت را خاموش کنید.
            </p>
          ) : (
            <NeighborhoodPicker />
          )}
        </div>
      </Section>

      {/* Deliberately a weight and not a "حداکثر ۱۰ دقیقه تا مترو" filter: the
          walking times are straight-line estimates, so a hard boundary would be
          a promise the data cannot keep. This says how much the estimate counts.
          Metro closeness is scored for every listing, which is why it stands on
          its own instead of being folded into the workplace commute. */}
      <Section icon={Train} title="نزدیکی به مترو" weight={weightSlot("metro")}>
        <Explainer label="چرا فیلتر نیست؟">
          فاصله‌ی پیاده تا نزدیک‌ترین ایستگاه مترو با این وزن در امتیاز هر ملک اثر می‌گذارد؛ هیچ ملکی به‌خاطر دوری
          از مترو حذف نمی‌شود.
        </Explainer>
      </Section>

      <Section
        icon={Briefcase}
        title="دسترسی به محل کار"
        weight={workplaceLocation ? { value: commuteLevel, onChange: setCommuteLevel } : undefined}
      >
        <div className="flex flex-col gap-2.5">
          {workplaceLocation ? (
            <div className="flex items-center justify-between gap-2 rounded-xl bg-brand-light px-3 py-2 text-xs text-brand">
              {/* Never the raw coordinates: "۳۵٫۷۵۹۱, ۵۱٫۴۱۰۲" tells the user
                  nothing about the place they just clicked. The name is filled
                  in as soon as the lookup answers. */}
              <span className="truncate font-medium">
                {workplaceLocation.name || "در حال یافتن نشانی..."}
              </span>
              <button
                type="button"
                onClick={() => setFilters({ workplaceLocation: null })}
                className="shrink-0 opacity-60 transition-opacity hover:opacity-100"
                aria-label="حذف محل کار"
              >
                <X size={14} />
              </button>
            </div>
          ) : (
            <p className="text-xs text-slate-500">محل کار را روی نقشه انتخاب کنید یا آدرس آن را جستجو کنید.</p>
          )}

          <form onSubmit={handleGeocodeSubmit} className="relative">
            <input
              type="text"
              value={addressQuery}
              onChange={(e) => setAddressQuery(e.target.value)}
              placeholder="جستجوی آدرس محل کار..."
              className={`${inputClass} pe-9`}
            />
            <button
              type="submit"
              disabled={isGeocoding || !addressQuery.trim()}
              className="absolute end-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition-colors hover:text-brand disabled:opacity-40"
              aria-label="جستجوی آدرس"
            >
              <Search size={14} />
            </button>
          </form>
          {geocodeError && <p className="text-xs text-red-600">{geocodeError}</p>}

          {/* The candidates, for the user to pick the one they meant. Each row
              wraps rather than truncating: two results in the same street
              differ only in the tail of the address, so cutting the tail off
              is cutting off the one part that tells them apart. */}
          {addressResults.length > 0 && (
            <ul className="max-h-56 overflow-y-auto overflow-x-hidden rounded-xl border border-line-soft">
              {addressResults.map((candidate) => (
                <li key={`${candidate.lat},${candidate.lon},${candidate.label}`}>
                  <button
                    type="button"
                    onClick={() => chooseAddress(candidate)}
                    className="flex w-full items-start gap-2 border-b border-line-soft px-3 py-2 text-start transition-colors last:border-b-0 hover:bg-slate-50"
                  >
                    <MapPin size={13} className="mt-0.5 shrink-0 text-slate-300" />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-xs font-medium text-slate-700">{candidate.label}</span>
                      {candidate.detail && (
                        <span className="block break-words text-[11px] leading-5 text-slate-500">{candidate.detail}</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={() => setFilters({ isPickingWorkplace: !isPickingWorkplace })}
            className={`flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
              isPickingWorkplace
                ? "border-brand bg-brand text-white"
                : "border-line text-slate-600 hover:border-brand"
            }`}
          >
            <Crosshair size={14} />
            {isPickingWorkplace ? "روی نقشه کلیک کنید..." : "انتخاب روی نقشه"}
          </button>

          {workplaceLocation && (
            <>
              <div className="flex gap-1.5">
                {COMMUTE_MODES.map(({ value, label, Icon }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setFilters({ commuteMode: value })}
                    className={`flex flex-1 items-center justify-center gap-1 rounded-xl border px-2 py-2 text-xs transition-colors ${
                      commuteMode === value
                        ? "border-brand bg-brand text-white"
                        : "border-line text-slate-600 hover:border-brand"
                    }`}
                  >
                    <Icon size={13} />
                    {label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </Section>
      </Group>

      {/* One weight for both fields, because the ranking has only ever had
          one: the budget criterion scores the هزینهٔ مؤثر ماهانه -- اجاره plus
          3% of ودیعه -- so weighting "ودیعه" alone was never a thing the
          engine could do. Saying so where the two sit together is the whole
          point of the grouping. The third dial in this band is نوع معامله's
          تبدیل preference, which does not change the total at all: it moves
          the split between the two numbers along the conversion line. */}
      <Group
        title="هزینه"
        summary={costSummary}
        hint="وزن روی هزینهٔ مؤثر ماهانه اعمال می‌شود — اجاره به‌علاوهٔ ۳٪ ودیعه — نه فقط یکی از این دو."
        weight={weightSlot("budget")}
      >
      <Section icon={Wallet} title="ودیعه" hint="میلیون تومان">
        <RangeInputs
          fromValue={tomanToMillionsInputValue(minDepositToman)}
          toValue={tomanToMillionsInputValue(depositToman)}
          onFromChange={(value) => setFilters({ minDepositToman: millionsToToman(value) })}
          onToChange={(value) => setFilters({ depositToman: millionsToToman(value) })}
        />
      </Section>

      <Section icon={Wallet} title="اجاره ماهیانه" hint="میلیون تومان">
        <RangeInputs
          fromValue={tomanToMillionsInputValue(minRentToman)}
          toValue={tomanToMillionsInputValue(rentToman)}
          onFromChange={(value) => setFilters({ minRentToman: millionsToToman(value) })}
          onToChange={(value) => setFilters({ rentToman: millionsToToman(value) })}
        />
      </Section>

      <Section icon={Handshake} title="نوع معامله">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-1.5">
            <Pill active={!fullRahnOnly && !convertibleOnly} onClick={selectDealShape(null)}>
              فرقی نمی‌کند
            </Pill>
            {DEAL_SHAPES.map(({ key, label, Icon }) => (
              <Pill key={key} active={dealState[key]} onClick={selectDealShape(key)}>
                <Icon size={13} />
                {label}
              </Pill>
            ))}
          </div>
          <div className={fullRahnOnly ? "opacity-45" : undefined}>
            <p className="mb-1.5 text-xs text-slate-500">
              {/* On a رهن کامل lease there is no monthly rent to move, so
                  asking which way to convert would be asking about something
                  that cannot happen. The choice is disabled rather than hidden
                  so the panel does not reflow under the user's cursor. */}
              {fullRahnOnly
                ? "در رهن کامل اجاره‌ای برای تبدیل وجود ندارد."
                : "اگر آگهی قابل تبدیل بود، کدام را ترجیح می‌دهید؟"}
            </p>
            <div className="grid grid-cols-3 gap-1.5">
              {FINANCIAL_PERSONAS.map(({ value, label, hint }) => (
                <button
                  key={value}
                  type="button"
                  title={hint}
                  disabled={fullRahnOnly}
                  onClick={() => setFilters({ financialPersona: value })}
                  className={`flex h-full flex-col items-center justify-center gap-0.5 rounded-xl border px-2 py-2 text-center text-xs leading-4 transition-colors ${
                    financialPersona === value && !fullRahnOnly
                      ? "border-brand bg-brand text-white"
                      : fullRahnOnly
                        ? "cursor-not-allowed border-line-soft bg-slate-50 text-slate-300"
                        : "border-line text-slate-600 hover:border-brand"
                  }`}
                >
                  <span className="font-medium">{label}</span>
                  <span
                    className={
                      fullRahnOnly ? "text-slate-300" : financialPersona === value ? "opacity-80" : "text-slate-500"
                    }
                  >
                    {hint}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </Section>
      </Group>

      <Group title="ویژگی‌های ملک" summary={featureSummary}>
      <Section icon={Ruler} title="متراژ" hint="متر مربع" weight={weightSlot("area")}>
        <RangeInputs
          fromValue={minAreaSqm > 0 ? String(minAreaSqm) : ""}
          toValue={maxAreaSqm > 0 ? String(maxAreaSqm) : ""}
          onFromChange={(value) => setFilters({ minAreaSqm: positiveOrZero(value) })}
          onToChange={(value) => setFilters({ maxAreaSqm: positiveOrZero(value) })}
        />
      </Section>

      <Section icon={BedDouble} title="تعداد اتاق">
        {/* Even columns rather than a wrapping row: at this width the pills
            broke five-and-one, which reads as two groups of options. */}
        <div className="grid grid-cols-6 gap-1.5">
          <Pill active={rooms === 0} onClick={() => setFilters({ rooms: 0 })}>
            همه
          </Pill>
          {Array.from({ length: MAX_ROOMS }, (_, i) => i + 1).map((n) => (
            <Pill key={n} active={rooms === n} onClick={() => setFilters({ rooms: n })}>
              {n}+
            </Pill>
          ))}
        </div>
      </Section>

      <Section icon={Building2} title="سن بنا و طبقه" weight={weightSlot("freshness")}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-1.5">
            {BUILD_AGE_PRESETS.map(({ label, maxAge }) => {
              const year = maxAge === null ? 0 : CURRENT_JALALI_YEAR - maxAge;
              return (
                <Pill key={label} active={minBuildYear === year} onClick={() => setFilters({ minBuildYear: year })}>
                  {label}
                </Pill>
              );
            })}
          </div>
          {/* «طبقه» sits outside the boxes, the way «متر مربع» does for
              متراژ: the two fields are the same از/تا pair as every other
              range in the panel, and repeating the noun inside each of them
              made this one filter look like a different control. */}
          <div className="flex items-center gap-2">
            <span className="shrink-0 text-xs font-medium text-slate-500">طبقه</span>
            <div className="min-w-0 flex-1">
              <RangeInputs
                fromValue={minFloor === null ? "" : String(minFloor)}
                toValue={maxFloor === null ? "" : String(maxFloor)}
                onFromChange={(value) => setFilters({ minFloor: value === "" ? null : Math.round(Number(value)) })}
                onToChange={(value) => setFilters({ maxFloor: value === "" ? null : Math.round(Number(value)) })}
              />
            </div>
          </div>
        </div>
      </Section>

      <Section icon={Sparkles} title="امکانات" weight={weightSlot("amenity")}>
        <div className="grid grid-cols-3 gap-1.5">
          {AMENITIES.map(({ key, label, Icon }) => (
            <Pill key={key} active={amenityState[key]} onClick={() => setFilters({ [key]: !amenityState[key] })}>
              <Icon size={13} />
              {label}
            </Pill>
          ))}
        </div>
      </Section>
      </Group>
      </div>

      {/* Pinned rather than appended: it is the way *out* of a filter, and a
          way out that only appears after three screens of scrolling is not
          one. It reports the result count too, so the number the filters
          produced is visible from wherever the user is editing them. */}
      <div className="flex shrink-0 items-center justify-between gap-3 border-t border-line bg-white/95 px-4 py-3 pb-20 backdrop-blur lg:pb-3">
        <span className="text-xs text-slate-600">
          {isLoading ? (
            "در حال جستجو…"
          ) : (
            <>
              <b className="text-sm font-bold text-slate-900">{totalCount.toLocaleString("fa-IR")}</b> ملک
              {activeFilterCount > 0 && ` با ${activeFilterCount.toLocaleString("fa-IR")} فیلتر`}
            </>
          )}
        </span>
        <button
          type="button"
          onClick={resetFilters}
          disabled={activeFilterCount === 0}
          className="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-slate-600 transition enabled:hover:border-line-strong enabled:hover:bg-slate-50 enabled:hover:text-slate-900 disabled:opacity-40"
        >
          <RotateCcw size={13} />
          پاک کردن فیلترها
        </button>
      </div>
    </div>
  );
}
