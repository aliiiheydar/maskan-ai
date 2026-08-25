// Mirrors backend/app/api/v1/schemas.py (see docs/API_SPEC.md, docs/DATA_SCHEMA.md).
// Keep these in sync with the backend DTOs -- they are the wire contract.

export type SearchMode = "intelligent" | "classic" | "map";

export interface BBoxFilter {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

export interface UnifiedSearchRequest {
  mode: SearchMode;
  query_text?: string;
  neighborhoods: string[];
  max_deposit_toman?: number;
  max_rent_toman?: number;
  min_area_sqm?: number;
  rooms?: number;
  requires_elevator: boolean;
  requires_parking: boolean;
  workplace_lat?: number;
  workplace_lon?: number;
  max_commute_mins?: number;
  bbox?: BBoxFilter;
  page: number;
  page_size: number;
}

// Full domain entity returned by GET /listings/{id} (docs/DATA_SCHEMA.md SS1).
// Distinct from ListingResult, which is the trimmed shape embedded in search results.
export interface Listing {
  id: string;
  title: string;
  description: string;
  neighborhood: string;
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
  created_at: string;
  embedding?: number[] | null;
}

export interface ListingResult {
  id: string;
  title: string;
  neighborhood: string;
  deposit_toman: number;
  rent_toman: number;
  area_sqm: number;
  floor: number;
  has_elevator: boolean;
  has_parking: boolean;
  lat: number;
  lon: number;
  dist_to_metro_mins: number;
  commute_to_work_mins?: number | null;
  utility_score: number;
  tier: 1 | 2;
  trade_off_rationale?: string | null;
}

export interface SearchResponse {
  natural_language_summary: string;
  tier_1_results: ListingResult[];
  tier_2_results: ListingResult[];
  total_count: number;
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
  max_deposit?: number;
  max_rent?: number;
  can_convert?: boolean;
  min_area_sqm?: number;
  min_rooms?: number;
  must_have_elevator?: boolean;
  must_have_parking?: boolean;
  target_neighborhoods?: string[];
  workplace_lat?: number;
  workplace_lon?: number;
  workplace_name?: string;
  max_commute_mins?: number;
  soft_preferences?: string[];
  soft_preference_summary?: string;
}

export type ChatSSEEvent =
  | { event: "token"; content: string }
  | { event: "state_update"; extracted_intent: ExtractedSearchIntent }
  | { event: "done" };

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
