import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";

import { useSearchStore } from "./useSearchStore";

import type { SearchResponse, UnifiedSearchRequest } from "@/types";

vi.mock("@/lib/api", () => ({
  searchListings: vi.fn(),
  getAppConfig: vi.fn(),
  getNeighborhoods: vi.fn(),
  getNeighborhoodAt: vi.fn(),
  getListing: vi.fn(),
  describeLocation: vi.fn(),
  streamChat: vi.fn(),
}));

const EMPTY_RESPONSE: SearchResponse = {
  natural_language_summary: "",
  results: [],
  total_count: 0,
  extracted_intent: null,
} as unknown as SearchResponse;

/** The request the store last sent to /search. */
const lastRequest = (): UnifiedSearchRequest =>
  vi.mocked(api.searchListings).mock.calls.at(-1)![0] as UnifiedSearchRequest;

const INITIAL = useSearchStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.searchListings).mockResolvedValue(EMPTY_RESPONSE);
  useSearchStore.setState(INITIAL, true);
});

describe("capability gating", () => {
  it("starts optimistic, so a configured deployment never blinks a mode disabled", () => {
    expect(useSearchStore.getState().aiSearchEnabled).toBe(true);
    expect(useSearchStore.getState().exploreMapEnabled).toBe(true);
  });

  it("adopts what the deployment reports", async () => {
    vi.mocked(api.getAppConfig).mockResolvedValue({ ai_search_enabled: false, explore_map_enabled: false });
    await useSearchStore.getState().loadAppConfig();
    expect(useSearchStore.getState().aiSearchEnabled).toBe(false);
    expect(useSearchStore.getState().exploreMapEnabled).toBe(false);
  });

  it("keeps the optimistic default when the config call fails", async () => {
    vi.mocked(api.getAppConfig).mockRejectedValue(new Error("offline"));
    await useSearchStore.getState().loadAppConfig();
    // An unreachable backend is the search's problem to report; the mode
    // switch must not turn itself off over it.
    expect(useSearchStore.getState().aiSearchEnabled).toBe(true);
    expect(useSearchStore.getState().exploreMapEnabled).toBe(true);
  });

  it("hands a user back to the filters when the mode they are in turns out to be off", async () => {
    useSearchStore.setState({ mode: "map" });
    vi.mocked(api.getAppConfig).mockResolvedValue({ ai_search_enabled: true, explore_map_enabled: false });
    await useSearchStore.getState().loadAppConfig();
    expect(useSearchStore.getState().mode).toBe("ranked");
  });

  it("refuses a mode the deployment does not offer", () => {
    useSearchStore.setState({ aiSearchEnabled: false, exploreMapEnabled: false });
    useSearchStore.getState().setMode("chat");
    expect(useSearchStore.getState().mode).toBe("ranked");
    useSearchStore.getState().setMode("map");
    expect(useSearchStore.getState().mode).toBe("ranked");
  });
});

describe("setMode", () => {
  it("clears the results when map-explore is entered, being a different search", async () => {
    useSearchStore.setState({ results: [{ id: "x" }] as never, totalCount: 1 });
    useSearchStore.getState().setMode("map");
    expect(useSearchStore.getState().results).toStrictEqual([]);
    expect(useSearchStore.getState().totalCount).toBe(0);
  });

  it("keeps the user's place when swapping between the two ranked modes", () => {
    // Same filters, same ranked search: only the input panel changes. Wiping
    // this would send the feed back to the top, drop the open listing and fly
    // the map home, all for a list that comes back the same.
    const place = {
      results: [{ id: "x" }] as never,
      totalCount: 1,
      page: 2,
      selectedListingId: "x",
      restoreBounds: [
        [35.7, 51.3],
        [35.8, 51.4],
      ] as never,
    };
    useSearchStore.setState(place);
    useSearchStore.getState().setMode("chat");
    expect(useSearchStore.getState()).toMatchObject({ ...place, mode: "chat" });

    useSearchStore.getState().setMode("ranked");
    expect(useSearchStore.getState()).toMatchObject({ ...place, mode: "ranked" });
  });

  it("does not re-search when swapping between the two ranked modes", () => {
    useSearchStore.getState().setMode("chat");
    expect(api.searchListings).not.toHaveBeenCalled();
  });

  it("leaves map-explore's first search to the map, which is what knows the viewport", () => {
    useSearchStore.getState().setMode("map");
    expect(api.searchListings).not.toHaveBeenCalled();
  });

  it("searches immediately on leaving map-explore, whose results do not carry over", async () => {
    useSearchStore.setState({ mode: "map" });
    useSearchStore.getState().setMode("ranked");
    await vi.waitFor(() => expect(api.searchListings).toHaveBeenCalled());
  });

  it("does nothing when the mode is already the current one", () => {
    useSearchStore.getState().setMode("ranked");
    expect(api.searchListings).not.toHaveBeenCalled();
  });
});

describe("the search request", () => {
  it("omits an unset numeric filter rather than sending a zero floor", async () => {
    await useSearchStore.getState().runSearch();
    const request = lastRequest();
    expect(request.min_deposit_toman).toBeUndefined();
    expect(request.max_rent_toman).toBeUndefined();
    expect(request.min_area_sqm).toBeUndefined();
  });

  it("sends the range the user typed", async () => {
    useSearchStore.setState({ minDepositToman: 100_000_000, depositToman: 500_000_000 });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().min_deposit_toman).toBe(100_000_000);
    expect(lastRequest().max_deposit_toman).toBe(500_000_000);
  });

  it("treats the viewport and the neighborhood selection as alternatives, never a conjunction", async () => {
    // Intersecting them would silently return nothing and look like a broken
    // filter, since the محله need not be anywhere the user can see.
    const bbox = { minLat: 35.7, minLon: 51.3, maxLat: 35.8, maxLon: 51.5 };
    useSearchStore.setState({ selectedNeighborhoods: ["992"], mapBBox: bbox, searchInViewport: true });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().neighborhoods).toStrictEqual([]);
    expect(lastRequest().bbox).toStrictEqual({
      min_lat: 35.7,
      min_lon: 51.3,
      max_lat: 35.8,
      max_lon: 51.5,
    });
  });

  it("uses the neighborhood selection when the viewport is not the search area", async () => {
    useSearchStore.setState({
      selectedNeighborhoods: ["992"],
      mapBBox: { minLat: 35.7, minLon: 51.3, maxLat: 35.8, maxLon: 51.5 },
      searchInViewport: false,
    });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().neighborhoods).toStrictEqual(["992"]);
    expect(lastRequest().bbox).toBeUndefined();
  });

  it("sends the zoom along with the box in map mode, since it decides pins vs badges", async () => {
    useSearchStore.setState({
      mode: "map",
      mapBBox: { minLat: 35.7, minLon: 51.3, maxLat: 35.8, maxLon: 51.5 },
      mapZoom: 15,
    });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().mode).toBe("map");
    expect(lastRequest().map_zoom).toBe(15);
  });

  it("only sends the free text in the conversational mode", async () => {
    useSearchStore.setState({ queryText: "نزدیک مترو" });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().query_text).toBeUndefined();

    useSearchStore.setState({ mode: "chat" });
    await useSearchStore.getState().runSearch();
    // Still the ranked path: free text alone cannot rank without a chat turn.
    expect(lastRequest().mode).toBe("ranked");
    expect(lastRequest().query_text).toBe("نزدیک مترو");
  });

  it("withholds the commute settings until there is a workplace to measure from", async () => {
    await useSearchStore.getState().runSearch();
    expect(lastRequest().max_commute_mins).toBeUndefined();
    expect(lastRequest().commute_mode).toBeUndefined();

    useSearchStore.setState({ workplaceLocation: { lat: 35.75, lon: 51.41, name: "" } });
    await useSearchStore.getState().runSearch();
    expect(lastRequest().workplace_lat).toBe(35.75);
    expect(lastRequest().max_commute_mins).toBeDefined();
  });
});

describe("results", () => {
  it("holds the page in the order the ranking sent it", async () => {
    // One list, not two: the server has already ordered it by utility, and
    // the store must not re-group or re-sort what it is handed.
    const page = [{ id: "a" }, { id: "b" }, { id: "c" }] as never;
    vi.mocked(api.searchListings).mockResolvedValue({ ...EMPTY_RESPONSE, results: page });
    await useSearchStore.getState().runSearch();
    expect(useSearchStore.getState().results).toStrictEqual(page);
  });

  it("reports a failed search in Persian rather than leaving the spinner up", async () => {
    vi.mocked(api.searchListings).mockRejectedValue(new Error(""));
    await useSearchStore.getState().runSearch();
    expect(useSearchStore.getState().isLoading).toBe(false);
    expect(useSearchStore.getState().searchError).toMatch(/[؀-ۿ]/);
  });

  it("continues paging from what is held, not from page arithmetic", async () => {
    // The bug this guards: the first page is larger than the rest, so an
    // offset computed from the page number re-served rows the feed already had.
    vi.mocked(api.searchListings).mockResolvedValue({
      ...EMPTY_RESPONSE,
      results: Array.from({ length: 60 }, (_, index) => ({ id: String(index) })) as never,
    });
    await useSearchStore.getState().runSearch();
    await useSearchStore.getState().loadMoreResults();
    expect(lastRequest().offset).toBe(60);
    expect(lastRequest().page).toBe(2);
  });
});
