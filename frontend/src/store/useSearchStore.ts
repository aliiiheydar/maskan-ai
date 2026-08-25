import { create } from "zustand";

import { searchListings, streamChat } from "@/lib/api";
import type { ChatMessage, ExtractedSearchIntent, ListingResult, SearchMode } from "@/types";

// Shape mandated by docs/FRONTEND_STATE.md SS1, extended with the async
// chat/search actions actually needed to wire the Chat and Filter panels
// together end-to-end (the doc only specifies the sync surface, not the
// network glue).
export interface FilterState {
  // Mode Selection
  mode: SearchMode;
  setMode: (mode: SearchMode) => void;

  // Search State
  queryText: string;
  depositToman: number;
  rentToman: number;
  minAreaSqm: number;
  hasElevator: boolean;
  hasParking: boolean;
  hasBalcony: boolean;
  selectedNeighborhoods: string[];

  // Work/Commute Hub
  workplaceLocation: { lat: number; lon: number; name: string } | null;
  maxCommuteMins: number;

  // Map & Viewport State
  mapBBox: { minLat: number; minLon: number; maxLat: number; maxLon: number } | null;
  selectedListingId: string | null;
  hoveredListingId: string | null;
  showTier2: boolean;

  // Result Set
  tier1Results: ListingResult[];
  tier2Results: ListingResult[];
  totalCount: number;
  naturalLanguageSummary: string;
  isLoading: boolean;
  searchError: string | null;

  // Chat State
  chatMessages: ChatMessage[];
  isChatStreaming: boolean;
  chatError: string | null;

  // Actions (per docs/FRONTEND_STATE.md)
  setFilters: (filters: Partial<FilterState>) => void;
  setSelectedListingId: (id: string | null) => void;
  setHoveredListingId: (id: string | null) => void;
  toggleTier2: () => void;
  syncFromExtractedIntent: (intent: ExtractedSearchIntent) => void;

  // Additional actions to actually drive the app
  runSearch: () => Promise<void>;
  sendChatMessage: (message: string) => Promise<void>;
}

export const useSearchStore = create<FilterState>((set, get) => ({
  mode: "classic",
  setMode: (mode) => set({ mode }),

  queryText: "",
  depositToman: 0,
  rentToman: 0,
  minAreaSqm: 0,
  hasElevator: false,
  hasParking: false,
  hasBalcony: false,
  selectedNeighborhoods: [],

  workplaceLocation: null,
  maxCommuteMins: 45,

  mapBBox: null,
  selectedListingId: null,
  hoveredListingId: null,
  showTier2: false,

  tier1Results: [],
  tier2Results: [],
  totalCount: 0,
  naturalLanguageSummary: "",
  isLoading: false,
  searchError: null,

  chatMessages: [],
  isChatStreaming: false,
  chatError: null,

  setFilters: (filters) => set(filters),

  setSelectedListingId: (id) => set({ selectedListingId: id }),

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
    if (intent.max_deposit !== undefined) patch.depositToman = intent.max_deposit;
    if (intent.max_rent !== undefined) patch.rentToman = intent.max_rent;
    if (intent.min_area_sqm !== undefined) patch.minAreaSqm = intent.min_area_sqm;
    if (intent.must_have_elevator !== undefined) patch.hasElevator = intent.must_have_elevator;
    if (intent.must_have_parking !== undefined) patch.hasParking = intent.must_have_parking;
    if (intent.target_neighborhoods !== undefined) patch.selectedNeighborhoods = intent.target_neighborhoods;
    if (intent.max_commute_mins !== undefined) patch.maxCommuteMins = intent.max_commute_mins;
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
      const response = await searchListings({
        mode: state.mode === "intelligent" ? "classic" : state.mode, // free-text search text alone can't drive ranking without a chat turn
        query_text: state.queryText || undefined,
        neighborhoods: state.selectedNeighborhoods,
        max_deposit_toman: state.depositToman || undefined,
        max_rent_toman: state.rentToman || undefined,
        min_area_sqm: state.minAreaSqm || undefined,
        requires_elevator: state.hasElevator,
        requires_parking: state.hasParking,
        workplace_lat: state.workplaceLocation?.lat,
        workplace_lon: state.workplaceLocation?.lon,
        max_commute_mins: state.workplaceLocation ? state.maxCommuteMins : undefined,
        bbox: state.mapBBox
          ? {
              min_lat: state.mapBBox.minLat,
              min_lon: state.mapBBox.minLon,
              max_lat: state.mapBBox.maxLat,
              max_lon: state.mapBBox.maxLon,
            }
          : undefined,
        page: 1,
        page_size: 30,
      });
      set({
        tier1Results: response.tier_1_results,
        tier2Results: response.tier_2_results,
        totalCount: response.total_count,
        naturalLanguageSummary: response.natural_language_summary,
        isLoading: false,
      });
    } catch (error) {
      set({ isLoading: false, searchError: error instanceof Error ? error.message : "جستجو با خطا مواجه شد." });
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
          chatError: error instanceof Error ? error.message : "ارتباط با دستیار هوشمند برقرار نشد.",
        };
      });
    }
  },
}));
