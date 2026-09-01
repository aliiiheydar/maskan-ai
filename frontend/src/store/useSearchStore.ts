import { create } from "zustand";

import {
  describeLocation,
  getAppConfig,
  getListing,
  getNeighborhoodAt,
  getNeighborhoods,
  searchListings,
  streamChat,
} from "@/lib/api";
import type {
  Listing,
  LivingKind,
  MapCluster,
  ChatMessage,
  CommuteMode,
  ExtractedSearchIntent,
  FinancialPersona,
  BBoxFilter,
  ListingResult,
  MapPoint,
  NeighborhoodSummary,
  SearchMode,
  UnifiedSearchRequest,
  CriteriaWeights,
  WeightedCriterion,
  WeightLevel,
} from "@/types";

/** Below this many Tier 1 results the feed opens the second tier on its own,
 * so a narrow search shows near misses instead of white space. */
const MIN_COMFORTABLE_RESULTS = 6;

const RESULTS_PAGE_SIZE = 30;

/** How many results the first page offers.
 *
 * A flat sixty, for every mode and every search area. Sizing this to the
 * area being searched was tried and reverted: measuring the box or summing
 * the selected neighborhoods' polygons put work on the critical path of every
 * keystroke, and it bought nothing a "بیشتر" click does not already give.
 * Every page after the first is the plain RESULTS_PAGE_SIZE -- this decides
 * how much is offered up front, not how fast more loads. */
const FIRST_PAGE_SIZE = 60;

/**
 * Each mode is a different search and sends a different request, so no filter
 * from one leaks into another.
 *
 * - map: the viewport, and nothing else. Exploring the map means "show me
 *   what's here", so the panel's filters are deliberately not applied -- the
 *   pin count in a cluster has to mean every listing in that area.
 * - classic: the filter panel. No viewport, or panning the map would silently
 *   hide matches; no free text, since there is no box to type it in.
 * - intelligent: the same filter fields (the chat writes into them) plus the
 *   text of the last turn, which the backend re-extracts intent from.
 */
function buildSearchRequest(state: FilterState, page: number, offset = 0): UnifiedSearchRequest {
  if (state.mode === "map") {
    return {
      mode: "map",
      neighborhoods: [],
      requires_elevator: false,
      requires_parking: false,
      requires_storage: false,
      requires_balcony: false,
      requires_images: false,
      full_rahn_only: false,
      living_kind: state.livingKind,
      convertible_only: false,
      bbox: state.mapBBox
        ? {
            min_lat: state.mapBBox.minLat,
            min_lon: state.mapBBox.minLon,
            max_lat: state.mapBBox.maxLat,
            max_lon: state.mapBBox.maxLon,
          }
        : undefined,
      // The zoom decides how much of the viewport comes back as pins rather
      // than as counted badges, so it travels with the box that defines them.
      map_zoom: state.mapZoom ?? undefined,
      page,
      offset,
      // The feed pages like any other mode. The pins do not: the map draws
      // response.map_points plus response.map_clusters, which together account
      // for every match, so the badges still agree with the count above the
      // feed.
      page_size: page === 1 ? FIRST_PAGE_SIZE : RESULTS_PAGE_SIZE,
    };
  }

  // "جستجو در محدوده نقشه": the visible rectangle replaces the neighborhood
  // selection as the search area. The two are alternatives, never a
  // conjunction -- a viewport intersected with a محله the user cannot see
  // would silently return nothing and look like a broken filter.
  const viewportArea = state.searchInViewport && state.mapBBox;

  return {
    // Free-text alone can't drive ranking without a chat turn, so the
    // intelligent mode's own searches run through the classic path with the
    // filters the conversation produced.
    mode: "classic",
    query_text: state.mode === "intelligent" ? state.queryText || undefined : undefined,
    neighborhoods: viewportArea ? [] : state.selectedNeighborhoods,
    bbox: viewportArea
      ? {
          min_lat: state.mapBBox!.minLat,
          min_lon: state.mapBBox!.minLon,
          max_lat: state.mapBBox!.maxLat,
          max_lon: state.mapBBox!.maxLon,
        }
      : undefined,
    min_deposit_toman: state.minDepositToman || undefined,
    max_deposit_toman: state.depositToman || undefined,
    min_rent_toman: state.minRentToman || undefined,
    max_rent_toman: state.rentToman || undefined,
    min_area_sqm: state.minAreaSqm || undefined,
    max_area_sqm: state.maxAreaSqm || undefined,
    rooms: state.rooms || undefined,
    min_floor: state.minFloor ?? undefined,
    max_floor: state.maxFloor ?? undefined,
    min_build_year: state.minBuildYear || undefined,
    requires_elevator: state.hasElevator,
    requires_parking: state.hasParking,
    requires_storage: state.hasStorage,
    requires_balcony: state.hasBalcony,
    requires_images: state.hasImages,
    full_rahn_only: state.fullRahnOnly,
    living_kind: state.livingKind,
    convertible_only: state.convertibleOnly,
    workplace_lat: state.workplaceLocation?.lat,
    workplace_lon: state.workplaceLocation?.lon,
    max_commute_mins: state.workplaceLocation ? state.maxCommuteMins : undefined,
    commute_mode: state.workplaceLocation ? state.commuteMode : undefined,
    commute_importance: state.commuteImportance,
    criteria_importance: state.criteriaWeights,
    financial_persona: state.financialPersona,
    page,
    offset,
    page_size: page === 1 ? FIRST_PAGE_SIZE : RESULTS_PAGE_SIZE,
  };
}

/** A full listing rendered as a feed card.
 *
 * Map-explore does not rank -- its pins are a filter, and the card hides the
 * ٪ badge in that mode -- so the score is 0 and the tier is 1 rather than
 * inventing a match this search never computed. */
function asResult(listing: Listing): ListingResult {
  return {
    ...listing,
    build_year: listing.build_year ?? null,
    is_full_rahn: listing.is_full_rahn ?? false,
    image_count: listing.image_count ?? 0,
    thumbnail_url: listing.images?.[0] ?? null,
    source_url: listing.source_url ?? null,
    dist_to_metro_mins: listing.metro_walk_mins,
    utility_score: 0,
    tier: 1,
  };
}

// Cleared whenever the search mode changes. The three modes are different
// searches -- map-explore is an unranked viewport filter, classic is a ranked
// boolean query, intelligent is a ranked conversational one -- so results and
// paging from one must never be left on screen under another.
const MODE_SCOPED_RESET = {
  tier1Results: [] as ListingResult[],
  tier2Results: [] as ListingResult[],
  mapPoints: [] as MapPoint[],
  mapClusters: [] as MapCluster[],
  focusedListing: null as ListingResult | null,
  totalCount: 0,
  page: 1,
  naturalLanguageSummary: "",
  searchError: null,
  showTier2: false,
  selectedListingId: null,
  hoveredListingId: null,
  mapBBox: null,
  mapZoom: null,
  searchInViewport: false,
  isPickingNeighborhood: false,
  restoreBounds: null,
  searchAreaBounds: null,
} as const;

// Shape mandated by docs/FRONTEND_STATE.md SS1, extended with the async
// chat/search actions actually needed to wire the Chat and Filter panels
// together end-to-end (the doc only specifies the sync surface, not the
// network glue).
export interface FilterState {
  // Mode Selection
  mode: SearchMode;
  setMode: (mode: SearchMode) => void;
  /** Whether the backend can serve the conversational search at all.
   *
   * It needs an OpenRouter key and the deployment may not have one, in which
   * case everything else -- the filters, the map, the ranking, the ٪ scores --
   * still works exactly as it does with one. So the mode is shown disabled
   * rather than hidden (its absence would read as a missing feature) and
   * rather than left enabled to fail on the user's first sentence. */
  aiSearchEnabled: boolean;
  loadAppConfig: () => Promise<void>;

  // Search State
  queryText: string;
  minDepositToman: number;
  depositToman: number;
  minRentToman: number;
  rentToman: number;
  minAreaSqm: number;
  maxAreaSqm: number;
  hasElevator: boolean;
  hasParking: boolean;
  hasBalcony: boolean;
  hasStorage: boolean;
  /** فقط آگهی‌های دارای عکس. */
  hasImages: boolean;
  /** فقط رهن کامل. */
  /** Which market is being searched: whole units, or shared homes, rooms and
   * dormitory beds. Never both -- per-person prices are not comparable with
   * whole-unit prices, so the two would rank against each other nonsensically. */
  livingKind: LivingKind;
  fullRahnOnly: boolean;
  /** فقط موارد قابل تبدیل. */
  convertibleOnly: boolean;
  rooms: number;
  minFloor: number | null;
  maxFloor: number | null;
  /** سال ساخت از (شمسی). */
  minBuildYear: number;
  /** How much each ranking criterion counts, in the three steps the panel
   * offers. These do not filter anything out -- they reorder what already
   * passed the filters -- so they are kept apart from the filter fields. */
  criteriaWeights: Record<WeightedCriterion, WeightLevel>;
  /** Which side of a تبدیل to push convertible listings toward. */
  financialPersona: FinancialPersona;
  /** Neighborhood keys, not titles -- the search area is resolved by key. */
  selectedNeighborhoods: string[];
  /** Armed by the picker's "انتخاب روی نقشه": the next map click adds (or
   * removes) whichever محله contains the clicked point. */
  isPickingNeighborhood: boolean;
  /** Adds/removes the neighborhood a coordinate falls in. Resolves null for a
   * point outside every polygon, which is reported, not silently ignored. */
  toggleNeighborhoodAt: (lat: number, lon: number) => Promise<string | null>;
  /** Search the visible map rectangle instead of the neighborhood selection.
   * The two are alternatives, so turning this on disables the picker. */
  searchInViewport: boolean;

  // Neighborhood catalog (GET /geo/neighborhoods), loaded once
  neighborhoodCatalog: NeighborhoodSummary[];
  loadNeighborhoods: () => Promise<void>;

  // Work/Commute Hub
  workplaceLocation: { lat: number; lon: number; name: string } | null;
  maxCommuteMins: number;
  /** 0..1. How much reachability should weigh in the ranking -- the travel
   * times are straight-line estimates, so only the searcher can say how much
   * to trust them. 0 drops the criterion entirely. */
  commuteImportance: number;
  commuteMode: CommuteMode;
  isPickingWorkplace: boolean;
  setWorkplaceFromMapClick: (lat: number, lon: number) => void;

  // Map & Viewport State
  mapBBox: { minLat: number; minLon: number; maxLat: number; maxLon: number } | null;
  /** The map's zoom when the viewport was last reported. */
  mapZoom: number | null;
  /** The viewport as it stood before the map flew to a listing, so the user
   * can get their search area back exactly -- not approximately -- after
   * looking at one property. Null when the map is showing the search itself. */
  restoreBounds: BBoxFilter | null;
  /** The rectangle the *search area itself* occupies -- the selected
   * neighborhoods' dissolved outline, published here by SearchAreaOverlay.
   * Null when the area is the whole city or the viewport.
   *
   * It exists because "back to the search area" has to mean the area, not the
   * last place the map happened to be looking: with neighborhoods chosen the
   * map is free to be panned anywhere without that changing what is searched,
   * so restoring the pre-click viewport returned the user to a rectangle that
   * was never the search. */
  searchAreaBounds: BBoxFilter | null;
  selectedListingId: string | null;
  hoveredListingId: string | null;
  showTier2: boolean;

  // Result Set
  tier1Results: ListingResult[];
  tier2Results: ListingResult[];
  /** Every match in map mode, pin-sized. Unpaginated on purpose. */
  mapPoints: MapPoint[];
  /** Counted cells for the parts of the viewport too dense to draw as pins. */
  mapClusters: MapCluster[];
  /** A selected pin whose listing is not on any loaded page of the feed.
   *
   * Map-explore plots the whole viewport but pages the feed 30 at a time, so
   * most pins have no card behind them. Rather than leaving those pins to a
   * different interaction than the rest, the one that was clicked is fetched
   * on its own and appended to the feed, where it behaves like any other card:
   * it scrolls into view, carries the مشاهده ملک button, and releases on a
   * second click. Only ever one -- it is replaced, not accumulated. */
  focusedListing: ListingResult | null;
  totalCount: number;
  page: number;
  naturalLanguageSummary: string;
  isLoading: boolean;
  isLoadingMore: boolean;
  searchError: string | null;
  loadMoreResults: () => Promise<void>;

  // Chat State
  chatMessages: ChatMessage[];
  isChatStreaming: boolean;
  chatError: string | null;

  // Actions (per docs/FRONTEND_STATE.md)
  setFilters: (filters: Partial<FilterState>) => void;
  /** Returns every filter to its default and re-runs the search. */
  resetFilters: () => void;
  setSelectedListingId: (id: string | null) => void;
  setHoveredListingId: (id: string | null) => void;
  toggleTier2: () => void;
  syncFromExtractedIntent: (intent: ExtractedSearchIntent) => void;

  // Additional actions to actually drive the app
  runSearch: () => Promise<void>;
  sendChatMessage: (message: string) => Promise<void>;
}

/** The share each criterion has when nobody has expressed a preference -- the
 * same neutral baseline the extractor prompt starts from. A weight the chat
 * inferred becomes a panel step by how far it moved from here. */
const NEUTRAL_CRITERION_WEIGHT: Record<WeightedCriterion, number> = {
  budget: 0.26,
  area: 0.16,
  amenity: 0.09,
  metro: 0.14,
  quality: 0.1,
  freshness: 0.06,
};

const RAISED_RATIO = 1.35;
const LOWERED_RATIO = 0.7;

/** The chat's weight vector, expressed in the three steps the filter panel
 * offers.
 *
 * Without this the assistant could read "ترجیحم اینه پول کمتری بدم" perfectly
 * and it would still change nothing: the ranking is driven by
 * `criteria_importance`, which only the panel used to write, so an inferred
 * weight vector reached the browser and stopped there. Going through the panel
 * state rather than straight into the request is deliberate -- the dials then
 * show what the chat understood, and the user can correct it.
 */
function importanceFromWeights(weights: CriteriaWeights): Partial<Record<WeightedCriterion, WeightLevel>> {
  const total = Object.values(weights).reduce<number>((sum, value) => sum + (value ?? 0), 0);
  if (total <= 0) return {};

  const levels: Partial<Record<WeightedCriterion, WeightLevel>> = {};
  (Object.keys(NEUTRAL_CRITERION_WEIGHT) as WeightedCriterion[]).forEach((criterion) => {
    // The panel's «نزدیکی به مترو» dial and the extractor's `commute` are the
    // same idea under two names; a model that splits it across both keys is
    // still talking about one thing.
    const share =
      criterion === "metro"
        ? ((weights.commute ?? 0) + (weights.metro ?? 0)) / total
        : (weights[criterion] ?? 0) / total;
    const ratio = share / NEUTRAL_CRITERION_WEIGHT[criterion];
    levels[criterion] = ratio >= RAISED_RATIO ? "high" : ratio <= LOWERED_RATIO ? "low" : "normal";
  });
  return levels;
}

/** Every filter at rest.
 *
 * Named once so three things agree: the store's initial state, the «پاک کردن
 * فیلترها» action, and any future read of "is anything actually set?". Before
 * this the first of those was the only one that existed, and a user who had
 * narrowed a search across eleven sections had no way back but a page reload.
 */
const DEFAULT_FILTERS = {
  queryText: "",
  minDepositToman: 0,
  depositToman: 0,
  minRentToman: 0,
  rentToman: 0,
  minAreaSqm: 0,
  maxAreaSqm: 0,
  hasElevator: false,
  hasParking: false,
  hasBalcony: false,
  hasStorage: false,
  hasImages: false,
  fullRahnOnly: false,
  livingKind: "standard",
  convertibleOnly: false,
  rooms: 0,
  minFloor: null,
  maxFloor: null,
  minBuildYear: 0,
  criteriaWeights: {
    budget: "normal",
    area: "normal",
    amenity: "normal",
    metro: "normal",
    quality: "normal",
    freshness: "normal",
  },
  financialPersona: "balanced",
  selectedNeighborhoods: [],
  isPickingNeighborhood: false,
  searchInViewport: false,
  workplaceLocation: null,
  maxCommuteMins: 45,
  commuteImportance: 0.5,
  commuteMode: "transit",
  isPickingWorkplace: false,
} satisfies Partial<FilterState>;

export const useSearchStore = create<FilterState>((set, get) => ({
  mode: "classic",

  // Optimistic: a configured deployment is the normal one, and starting from
  // `false` would blink the mode switch disabled on every load. An
  // unconfigured one corrects this a moment later, and until it does the
  // button behaves as it always has -- the backend answers a chat turn with
  // its own Persian "not configured" notice.
  aiSearchEnabled: true,
  loadAppConfig: async () => {
    try {
      const { ai_search_enabled } = await getAppConfig();
      set({ aiSearchEnabled: ai_search_enabled });
      // A user parked in a mode that just turned out to be unavailable is
      // handed back the filters rather than left on a panel that cannot reply.
      if (!ai_search_enabled && get().mode === "intelligent") get().setMode("classic");
    } catch {
      // Unreachable backend is the search's problem to report, not the mode
      // switch's; the capability keeps its optimistic default.
    }
  },

  setMode: (mode) => {
    if (get().mode === mode) return;
    if (mode === "intelligent" && !get().aiSearchEnabled) return;
    set({ mode, ...MODE_SCOPED_RESET, isLoading: true });
    // Map mode's first search is issued by the map itself, which is the only
    // thing that knows the viewport being searched (see BBoxSync).
    if (mode !== "map") void get().runSearch();
  },

  ...DEFAULT_FILTERS,

  neighborhoodCatalog: [],
  loadNeighborhoods: async () => {
    if (get().neighborhoodCatalog.length > 0) return;
    try {
      set({ neighborhoodCatalog: await getNeighborhoods() });
    } catch {
      // The picker degrades to "no neighborhoods offered"; every other
      // filter still works, so this must never surface as a search error.
    }
  },

  setWorkplaceFromMapClick: (lat, lon) => {
    // The pin lands immediately; its name arrives when the geocoder answers.
    // Blocking the pin on a network round-trip would make picking a workplace
    // feel broken on a slow connection, and the coordinates are never what
    // the panel shows -- "35.7591, 51.4102" tells the user nothing about
    // where they just clicked.
    set({ workplaceLocation: { lat, lon, name: "" }, isPickingWorkplace: false });
    void describeLocation(lat, lon).then((name) => {
      if (!name) return;
      const current = get().workplaceLocation;
      // Only if the pin is still the one this lookup was for -- a second
      // click while the first was in flight must not be relabelled.
      if (current && current.lat === lat && current.lon === lon && !current.name) {
        set({ workplaceLocation: { ...current, name } });
      }
    });
  },

  toggleNeighborhoodAt: async (lat, lon) => {
    const found = await getNeighborhoodAt(lat, lon).catch(() => null);
    if (!found) return null;
    const selected = get().selectedNeighborhoods;
    set({
      selectedNeighborhoods: selected.includes(found.key)
        ? selected.filter((key) => key !== found.key)
        : [...selected, found.key],
    });
    return found.title;
  },

  mapBBox: null,
  mapZoom: null,
  restoreBounds: null,
  searchAreaBounds: null,
  selectedListingId: null,
  hoveredListingId: null,
  showTier2: false,

  tier1Results: [],
  tier2Results: [],
  mapPoints: [],
  mapClusters: [],
  focusedListing: null,
  totalCount: 0,
  page: 1,
  naturalLanguageSummary: "",
  isLoading: false,
  isLoadingMore: false,
  searchError: null,

  chatMessages: [],
  isChatStreaming: false,
  chatError: null,

  setFilters: (filters) => set(filters),

  /** Back to an unfiltered search, without losing the mode or the map.
   *
   * Deliberately not a page reload: the neighborhood catalog, the chat
   * transcript and the map's own viewport are not filters, and discarding them
   * would make "clear the filters" cost the user more than it gives. */
  resetFilters: () => {
    set({ ...DEFAULT_FILTERS, selectedListingId: null, focusedListing: null, restoreBounds: null, page: 1 });
    void get().runSearch();
  },

  setSelectedListingId: (id) => {
    set({ selectedListingId: id });
    if (!id) {
      set({ focusedListing: null });
      return;
    }
    const state = get();
    if ([...state.tier1Results, ...state.tier2Results].some((listing) => listing.id === id)) {
      set({ focusedListing: null });
      return;
    }
    if (state.focusedListing?.id === id) return;
    void getListing(id)
      .then((listing) => {
        // The selection may have moved on while this was in flight; the card
        // that arrives then belongs to nothing on screen.
        if (get().selectedListingId === id) set({ focusedListing: asResult(listing) });
      })
      .catch(() => set({ focusedListing: null }));
  },

  setHoveredListingId: (id) => set({ hoveredListingId: id }),

  toggleTier2: () => set((state) => ({ showTier2: !state.showTier2 })),

  // Applies an LLM-extracted intent onto the classic filter state, so the
  // sliders/checkboxes visually reflect what the chat understood (the
  // "chat -> filters" half of the bidirectional sync in
  // docs/FRONTEND_STATE.md SS2). Only fields the intent actually set are
  // applied -- the backend serializes with exclude_unset, so undefined here
  // genuinely means "the user didn't mention this," not "clear it."
  syncFromExtractedIntent: (intent) => {
    const patch: Partial<FilterState> = {};
    if (intent.min_deposit !== undefined) patch.minDepositToman = intent.min_deposit;
    if (intent.max_deposit !== undefined) patch.depositToman = intent.max_deposit;
    if (intent.min_rent !== undefined) patch.minRentToman = intent.min_rent;
    if (intent.max_rent !== undefined) patch.rentToman = intent.max_rent;
    if (intent.min_area_sqm !== undefined) patch.minAreaSqm = intent.min_area_sqm;
    if (intent.max_area_sqm !== undefined) patch.maxAreaSqm = intent.max_area_sqm;
    if (intent.must_have_elevator !== undefined) patch.hasElevator = intent.must_have_elevator;
    if (intent.must_have_parking !== undefined) patch.hasParking = intent.must_have_parking;
    if (intent.must_have_storage !== undefined) patch.hasStorage = intent.must_have_storage;
    if (intent.must_have_balcony !== undefined) patch.hasBalcony = intent.must_have_balcony;
    if (intent.must_have_images !== undefined) patch.hasImages = intent.must_have_images;
    if (intent.full_rahn_only !== undefined) patch.fullRahnOnly = intent.full_rahn_only;
    if (intent.living_kind !== undefined) patch.livingKind = intent.living_kind;
    if (intent.convertible_only !== undefined) patch.convertibleOnly = intent.convertible_only;
    if (intent.min_floor !== undefined) patch.minFloor = intent.min_floor;
    if (intent.max_floor !== undefined) patch.maxFloor = intent.max_floor;
    if (intent.min_build_year !== undefined) patch.minBuildYear = intent.min_build_year;
    if (intent.commute_importance !== undefined) patch.commuteImportance = intent.commute_importance;
    if (intent.financial_persona !== undefined) patch.financialPersona = intent.financial_persona;
    // Keys only: a place name the backend couldn't resolve to a polygon is not
    // a selectable search area, and putting it in the filter would render as a
    // chip the user can't act on.
    if (intent.target_neighborhood_keys !== undefined) {
      patch.selectedNeighborhoods = intent.target_neighborhood_keys;
    }
    if (intent.weights) {
      patch.criteriaWeights = { ...get().criteriaWeights, ...importanceFromWeights(intent.weights) };
    }
    if (intent.max_commute_mins !== undefined) patch.maxCommuteMins = intent.max_commute_mins;
    if (intent.commute_mode !== undefined) patch.commuteMode = intent.commute_mode;
    if (intent.min_rooms !== undefined) patch.rooms = intent.min_rooms;
    if (intent.workplace_lat !== undefined && intent.workplace_lon !== undefined) {
      patch.workplaceLocation = {
        lat: intent.workplace_lat,
        lon: intent.workplace_lon,
        name: intent.workplace_name ?? "",
      };
    }
    set(patch);
  },

  // Issues /search using the current filter state (the "filters -> search
  // context" half of the sync). Called directly by slider/checkbox changes
  // and after a chat turn finishes extracting intent.
  runSearch: async () => {
    const state = get();
    set({ isLoading: true, searchError: null });
    try {
      const response = await searchListings(buildSearchRequest(state, 1));
      set({
        tier1Results: response.tier_1_results,
        tier2Results: response.tier_2_results,
        mapPoints: response.map_points ?? [],
        mapClusters: response.map_clusters ?? [],
        totalCount: response.total_count,
        page: 1,
        naturalLanguageSummary: response.natural_language_summary,
        isLoading: false,
        // A narrow search can leave Tier 1 with three results and a collapsed
        // panel underneath, which reads as "there is nothing here" when there
        // are in fact two hundred near misses. Opening the second tier fills
        // the feed *without* relabelling anything: those listings still carry
        // their own match percentage and their own tier heading, so the
        // ranking never claims a listing is a better fit than it scored.
        showTier2: response.tier_1_results.length < MIN_COMFORTABLE_RESULTS,
      });
    } catch (error) {
      set({
        isLoading: false,
        searchError:
          error instanceof Error && error.message ? error.message : "جستجو با خطا مواجه شد. لطفاً دوباره تلاش کنید.",
      });
    }
  },

  // Fetches the next page and appends it to the existing tier1/tier2 arrays,
  // rather than replacing them (unlike runSearch, which always starts fresh
  // from page 1).
  loadMoreResults: async () => {
    const state = get();
    const nextPage = state.page + 1;
    // Where to continue from is how many results are held, not which page
    // this is: the first page is FIRST_PAGE_SIZE and the rest are smaller, so
    // page arithmetic on the server's side asked for row 30 while the feed
    // already had sixty -- and rows 30..59 arrived a second time, appended
    // below themselves at the higher percentages they had ranked at.
    const loaded = state.tier1Results.length + state.tier2Results.length;
    set({ isLoadingMore: true, searchError: null });
    try {
      const response = await searchListings(buildSearchRequest(state, nextPage, loaded));
      set({
        tier1Results: [...state.tier1Results, ...response.tier_1_results],
        tier2Results: [...state.tier2Results, ...response.tier_2_results],
        totalCount: response.total_count,
        page: nextPage,
        isLoadingMore: false,
      });
    } catch (error) {
      set({
        isLoadingMore: false,
        searchError:
          error instanceof Error && error.message ? error.message : "جستجو با خطا مواجه شد. لطفاً دوباره تلاش کنید.",
      });
    }
  },

  // Streams a chat turn, appends tokens live, applies the extracted intent
  // once the model finishes, then re-runs search so the feed/map reflect the
  // new understanding (the "chat -> filters -> results" full loop).
  sendChatMessage: async (message) => {
    const userMessage: ChatMessage = { role: "user", content: message };
    const history = get().chatMessages;
    set({
      chatMessages: [...history, userMessage, { role: "assistant", content: "" }],
      isChatStreaming: true,
      chatError: null,
    });

    const appendToAssistant = (delta: string) => {
      set((state) => {
        const messages = [...state.chatMessages];
        const last = messages[messages.length - 1];
        messages[messages.length - 1] = { ...last, content: last.content + delta };
        return { chatMessages: messages };
      });
    };

    try {
      for await (const event of streamChat({ message, history })) {
        if (event.event === "token") {
          appendToAssistant(event.content);
        } else if (event.event === "state_update") {
          get().syncFromExtractedIntent(event.extracted_intent);
        } else if (event.event === "error") {
          // Reported in-band and already written in Persian by the backend.
          // Drop the assistant bubble if it never received a token, so the
          // notice below is the only thing describing what happened.
          set((state) => {
            const messages = [...state.chatMessages];
            const last = messages[messages.length - 1];
            if (last?.role === "assistant" && last.content === "") messages.pop();
            return { chatMessages: messages, chatError: event.message };
          });
        } else if (event.event === "done") {
          set({ isChatStreaming: false });
          await get().runSearch();
        }
      }
    } catch (error) {
      set((state) => {
        // Drop the empty trailing assistant placeholder -- otherwise it's
        // left permanently showing a spinner since no "done" event arrives
        // on this path to end the stream.
        const messages = [...state.chatMessages];
        const last = messages[messages.length - 1];
        if (last?.role === "assistant" && last.content === "") messages.pop();
        return {
          chatMessages: messages,
          isChatStreaming: false,
          chatError:
            error instanceof Error && error.message
              ? error.message
              : "ارتباط با دستیار هوشمند برقرار نشد. لطفاً دوباره تلاش کنید.",
        };
      });
    }
  },
}));