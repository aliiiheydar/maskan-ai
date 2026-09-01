// Mirrors backend/app/api/v1/schemas.py (see docs/API_SPEC.md, docs/DATA_SCHEMA.md).
// Keep these in sync with the backend DTOs -- they are the wire contract.

export type SearchMode = "intelligent" | "classic" | "map";

export type CommuteMode = "walk" | "transit" | "drive";

/** Which side of a تبدیل the user wants to be pushed toward. */
export type FinancialPersona = "prefer_higher_rent" | "prefer_higher_deposit" | "balanced";

export interface BBoxFilter {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

export interface UnifiedSearchRequest {
  mode: SearchMode;
  query_text?: string;
  /** Neighborhood keys from GET /geo/neighborhoods. */
  neighborhoods: string[];
  min_deposit_toman?: number;
  max_deposit_toman?: number;
  min_rent_toman?: number;
  max_rent_toman?: number;
  min_area_sqm?: number;
  max_area_sqm?: number;
  rooms?: number;
  min_floor?: number;
  max_floor?: number;
  /** سال ساخت (شمسی) floor -- "نوساز" is a year, not an age. */
  min_build_year?: number;
  requires_elevator: boolean;
  requires_parking: boolean;
  requires_storage: boolean;
  requires_balcony: boolean;
  requires_images: boolean;
  full_rahn_only: boolean;
  convertible_only: boolean;
  workplace_lat?: number;
  workplace_lon?: number;
  max_commute_mins?: number;
  commute_mode?: CommuteMode;
  /** 0..1 dial on how much reachability weighs in the ranking. */
  commute_importance?: number;
  /** Per-criterion ranking importance from the panel's three-step pickers.
   * Criteria left out keep their documented default share. */
  criteria_importance?: Partial<Record<WeightedCriterion, WeightLevel>>;
  financial_persona?: FinancialPersona;
  living_kind?: LivingKind;
  bbox?: BBoxFilter;
  /** The map's zoom (fractional -- zooming is continuous), so the server
   * knows which cells to open into pins. */
  map_zoom?: number;
  page: number;
  page_size: number;
  /** Where this page starts. Sent because the feed's first page is bigger
   * than the ones after it, so (page - 1) * page_size does not say where the
   * next one begins -- without it the server re-sent rows the feed already
   * had. */
  offset?: number;
}

// Full domain entity returned by GET /listings/{id} (docs/DATA_SCHEMA.md SS1).
// Distinct from ListingResult, which is the trimmed shape embedded in search results.
export interface Listing {
  id: string;
  title: string;
  description: string;
  neighborhood: string;
  district?: string | null;
  deposit_toman: number;
  rent_toman: number;
  effective_monthly_cost: number;
  can_convert: boolean;
  area_sqm: number;
  rooms: number;
  floor: number;
  total_floors: number;
  has_elevator: boolean;
  has_parking: boolean;
  has_balcony: boolean;
  has_storage: boolean;
  building_age_years: number;
  lat: number;
  lon: number;
  h3_index: string;
  nearest_metro_id: string;
  nearest_metro_name: string;
  dist_to_metro_meters: number;
  metro_walk_mins: number;
  in_tarh_terafik: boolean;
  in_tarh_aloodegi: boolean;

  /** Everything the real Divar feed carries that the ranked card has no room
   * for. All optional: a synthetic listing has none of it. */
  build_year?: number | null;
  is_full_rahn?: boolean;
  convertible_deposit_max_toman?: number | null;
  location_precision?: string | null;
  location_radius_meters?: number | null;
  units_per_floor?: number | null;
  min_contract_months?: number | null;
  direction?: string | null;
  kitchen_type?: string | null;
  is_renovated?: boolean;
  is_furnished?: boolean;
  has_pool?: boolean;
  has_sauna?: boolean;
  has_jacuzzi?: boolean;
  pets_policy?: "allowed" | "not_allowed" | "negotiable" | null;
  /** Divar's other_features grouped by facet: cooling, heating, floor_material, ... */
  features?: Record<string, string[]>;
  suitable_for?: string[];
  /** Divar's مشخصات table verbatim. */
  attributes?: Record<string, string>;
  /** Per field, where the value came from -- "listing_text" means we read it
   * out of the advertiser's prose rather than a field they filled in. */
  provenance?: Record<string, string>;
  published_text?: string | null;
  source?: string;
  source_url?: string | null;
  image_count?: number;
  images?: string[];
  images_are_authentic?: boolean;

  created_at: string;
  embedding?: number[] | null;
}

export interface ListingResult {
  id: string;
  title: string;
  neighborhood: string;
  neighborhood_key?: string | null;
  district?: string | null;
  deposit_toman: number;
  rent_toman: number;
  area_sqm: number;
  rooms: number;
  floor: number;
  total_floors: number;
  build_year?: number | null;
  has_elevator: boolean;
  has_parking: boolean;
  has_storage: boolean;
  has_balcony: boolean;
  can_convert: boolean;
  is_full_rahn: boolean;
  image_count: number;
  thumbnail_url?: string | null;
  source_url?: string | null;
  /** The deposit/rent split the engine assumed to make this fit the budget --
   * present only when a تبدیل was needed, so the card can say so. */
  suggested_deposit_toman?: number | null;
  suggested_rent_toman?: number | null;
  lat: number;
  lon: number;
  dist_to_metro_mins: number;
  commute_to_work_mins?: number | null;
  utility_score: number;
  tier: 1 | 2;
  trade_off_rationale?: string | null;
  /** No other tier-1 pick beats this one on cost, metro walk, and area at once. */
  is_pareto_optimal?: boolean;
  /** Per-criterion sub-utilities behind utility_score. */
  score_breakdown?: Record<string, number>;
}

/** A listing reduced to what a map pin needs. Map-explore plots every match,
 * so the pins cannot be the paginated ListingResult objects -- the card
 * details are fetched per listing when a pin is clicked. */
export interface MapPoint {
  id: string;
  lat: number;
  lon: number;
  tier: 1 | 2;
}

/** A counted group of matches in one part of the viewport, with the rectangle
 * the map flies to when its badge is clicked. Built server-side (see
 * app/search/map_clusters.py) so a city-wide pan sends a dozen numbers instead
 * of every pin in Tehran. */
export interface MapCluster {
  lat: number;
  lon: number;
  count: number;
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

/** Which market a search is against. Shared homes, rooms and dormitory beds
 * are priced per person, so they are chosen explicitly rather than mixed into
 * the whole-unit results. */
export type LivingKind = "standard" | "shared";

export interface SearchResponse {
  natural_language_summary: string;
  tier_1_results: ListingResult[];
  tier_2_results: ListingResult[];
  /** Every match, unpaginated. Empty outside map mode. */
  map_points: MapPoint[];
  map_clusters: MapCluster[];
  total_count: number;
  /** What the backend actually searched with, after free-text extraction and
   * neighborhood resolution -- reflected back into the filter panel. */
  applied_intent?: ExtractedSearchIntent | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatStreamRequest {
  message: string;
  history: ChatMessage[];
}

// backend/app/llm's ExtractedSearchIntent (docs/DATA_SCHEMA.md SS2). All fields
// optional on the wire since the endpoint serializes with exclude_unset=True.
export interface ExtractedSearchIntent {
  min_deposit?: number;
  max_deposit?: number;
  min_rent?: number;
  max_rent?: number;
  can_convert?: boolean;
  min_area_sqm?: number;
  max_area_sqm?: number;
  min_rooms?: number;
  min_floor?: number;
  max_floor?: number;
  min_build_year?: number;
  must_have_elevator?: boolean;
  must_have_parking?: boolean;
  must_have_storage?: boolean;
  must_have_balcony?: boolean;
  must_have_images?: boolean;
  full_rahn_only?: boolean;
  /** Whole unit vs. a room / shared home -- two separate markets, so the chat
   * has to be able to switch between them the way the filter panel can. */
  living_kind?: LivingKind;
  convertible_only?: boolean;
  /** Place names exactly as the user said them. */
  target_neighborhoods?: string[];
  /** Those names resolved onto real neighborhood polygons. */
  target_neighborhood_keys?: string[];
  workplace_lat?: number;
  workplace_lon?: number;
  workplace_name?: string;
  max_commute_mins?: number;
  commute_mode?: CommuteMode;
  commute_importance?: number;
  financial_persona?: FinancialPersona;
  soft_preferences?: string[];
  soft_preference_summary?: string;
  /** Per-criterion ranking weights the assistant inferred from the
   * conversation; absent on the classic-filter path. */
  weights?: CriteriaWeights | null;
}

/** How much one ranking criterion should count, in the three steps the
 * filter panel offers. The backend turns these into weight multipliers
 * (app/search/scoring.py::IMPORTANCE_MULTIPLIERS). */
export type WeightLevel = "low" | "normal" | "high";

/** The criteria the classic panel can be weighted on -- those that have a
 * filter section to attach the control to. */
export type WeightedCriterion = "budget" | "area" | "amenity" | "metro" | "quality" | "freshness";

/** MAUT sub-utility weights (see backend app/search/scoring.py). */
export interface CriteriaWeights {
  budget?: number;
  value?: number;
  area?: number;
  amenity?: number;
  metro?: number;
  commute?: number;
  quality?: number;
  freshness?: number;
  soft?: number;
}

export type ChatSSEEvent =
  | { event: "token"; content: string }
  | { event: "state_update"; extracted_intent: ExtractedSearchIntent }
  /** A failure the backend chose to report in-band, in Persian, rather than
   * by aborting the stream (which reaches the browser as "network error"). */
  | { event: "error"; message: string }
  | { event: "done" };

// Minimal structural GeoJSON geometry type -- just enough to hand straight
// to react-leaflet's <GeoJSON>, without pulling in a full @types/geojson dep.
export interface GeoJSONGeometry {
  type: "Polygon" | "MultiPolygon";
  coordinates: number[][][] | number[][][][];
}

export interface IsochroneResponse {
  mode: CommuteMode;
  geometry: GeoJSONGeometry | null;
}

export interface CongestionZone {
  zone: "tarh_terafik" | "tarh_aloodegi";
  label: string;
  geometry: GeoJSONGeometry;
}

/** One neighborhood without its polygon (GET /geo/neighborhoods): enough to
 * populate the picker and to place the map's neighborhood labels. */
export interface NeighborhoodSummary {
  key: string;
  title: string;
  subtitle: string;
  center_lat: number;
  center_lon: number;
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
  /** Footprint in km2, used to size the first page of results to the area
   * actually being searched. */
  area_sqkm: number;
}

export interface NeighborhoodShape {
  key: string;
  title: string;
  geometry: GeoJSONGeometry;
}

/** The selected neighborhoods dissolved into one outline (GET
 * /geo/neighborhoods/area). `geometry` is null when nothing is selected. */
export interface SearchArea {
  keys: string[];
  geometry: GeoJSONGeometry | null;
}

export interface CityBoundary {
  name: string;
  geometry: GeoJSONGeometry;
}

export interface TransitStation {
  id: string;
  name: string;
  name_en?: string | null;
  lat: number;
  lon: number;
  type: "metro" | "brt";
  lines: string[];
  has_elevator: boolean;
  relations: string[];
}
