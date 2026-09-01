import type {
  ChatSSEEvent,
  ChatStreamRequest,
  CityBoundary,
  CommuteMode,
  CongestionZone,
  IsochroneResponse,
  Listing,
  NeighborhoodShape,
  NeighborhoodSummary,
  SearchArea,
  SearchResponse,
  TransitStation,
  UnifiedSearchRequest,
} from "@/types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

// Tehran bbox per CLAUDE.md, used to bias/bound Nominatim geocoding results.
const TEHRAN_VIEWBOX = "51.1000,35.8500,51.6000,35.5500"; // left,top,right,bottom

/** One candidate answer to an address search: where it is, and how to name it.
 *
 * `label` is the part a person recognises (the street, the square, the
 * building) and `detail` is everything Nominatim adds after it. They are kept
 * apart because a picker has to show the first prominently and the second as
 * the thing that tells two similarly-named places apart.
 */
export interface AddressCandidate {
  lat: number;
  lon: number;
  label: string;
  detail: string;
}

/** How many candidates an address search offers. Enough that the right place
 * is almost always among them, few enough to read without scrolling. */
const ADDRESS_RESULT_LIMIT = 6;

/**
 * Free-text address -> a ranked list of candidates via OpenStreetMap's public
 * Nominatim geocoder. No API key needed, but this is best-effort/low-volume
 * client-side use only (lookups on explicit user submit, no bulk/cached calls)
 * -- see https://operations.osmfoundation.org/policies/nominatim/.
 *
 * A list rather than the single best hit: Nominatim's first result is the one
 * *it* ranks highest, which for a common street name in a city of nine million
 * is regularly not the one the user meant. Silently taking it put a workplace
 * pin somewhere the user never chose and gave them nothing to correct it with.
 */
export async function searchTehranAddresses(query: string): Promise<AddressCandidate[]> {
  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("format", "json");
  url.searchParams.set("q", query);
  url.searchParams.set("viewbox", TEHRAN_VIEWBOX);
  url.searchParams.set("bounded", "1");
  url.searchParams.set("limit", String(ADDRESS_RESULT_LIMIT));

  const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error("جستجوی آدرس با خطا مواجه شد.");
  }
  const results: { lat: string; lon: string; display_name: string }[] = await response.json();
  return results.map((result) => {
    const [head, ...rest] = result.display_name.split("،").flatMap((part) => part.split(","));
    return {
      lat: parseFloat(result.lat),
      lon: parseFloat(result.lon),
      label: head.trim(),
      detail: rest.map((part) => part.trim()).filter(Boolean).join("، "),
    };
  });
}

/** How many words of a reverse-geocoded address are worth showing. A pin on
 * the map needs to say *where* it is, not to reproduce a postal address --
 * "میدان ونک" identifies the spot; the full Nominatim display_name is a line
 * of text nobody reads. */
const ADDRESS_MAX_WORDS = 3;

function shortAddressFrom(address: Record<string, string | undefined>): string | null {
  // Most specific first: the street is what a person would say, and the
  // neighborhood is the fallback when the click lands off any named way.
  const parts = [
    address.road ?? address.pedestrian ?? address.square ?? address.footway,
    address.neighbourhood ?? address.suburb ?? address.quarter,
  ].filter((part): part is string => Boolean(part && part.trim()));
  // Parts are added whole or not at all. Trimming the joined string to a word
  // count instead would cut a name in half -- "گلدیس چهاردهم، شهرک" for
  // "گلدیس چهاردهم، شهرک آزمایش" -- which reads as a typo, not as a place.
  const label: string[] = [];
  let words = 0;
  for (const part of parts) {
    const length = part.trim().split(/\s+/).length;
    if (label.length > 0 && words + length > ADDRESS_MAX_WORDS) break;
    label.push(part.trim());
    words += length;
  }
  return label.length > 0 ? label.join("، ") : null;
}

/**
 * A coordinate turned into a two-or-three-word place name.
 *
 * Tried against OpenStreetMap first, because it knows street and square names;
 * a coordinate pair is not an answer to "where is your workplace". When that
 * is unavailable -- offline, rate-limited, or the point is simply unmapped --
 * the app's own neighborhood polygons still name the محله, which is coarser
 * but never wrong. Returns null only if both have nothing to say.
 */
export async function describeLocation(lat: number, lon: number): Promise<string | null> {
  try {
    const url = new URL("https://nominatim.openstreetmap.org/reverse");
    url.searchParams.set("format", "jsonv2");
    url.searchParams.set("lat", String(lat));
    url.searchParams.set("lon", String(lon));
    // Street level: finer than this returns house numbers, coarser returns
    // "Tehran", and neither is what the pin's label should read.
    url.searchParams.set("zoom", "17");
    url.searchParams.set("accept-language", "fa");

    const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
    if (response.ok) {
      const body: { address?: Record<string, string | undefined> } = await response.json();
      const short = body.address ? shortAddressFrom(body.address) : null;
      if (short) return short;
    }
  } catch {
    // Fall through to the local polygons below.
  }

  try {
    const neighborhood = await getNeighborhoodAt(lat, lon);
    return neighborhood?.title ?? null;
  } catch {
    return null;
  }
}

/** Persian fallbacks for the cases where there is no server message to show:
 * the request never reached the backend, or it answered without a detail. */
const OFFLINE_MESSAGE =
  "ارتباط با سرور برقرار نشد. اتصال اینترنت خود را بررسی کنید و دوباره تلاش کنید.";
const SERVER_ERROR_MESSAGE = "سرور پاسخ نداد. لطفاً چند لحظه دیگر دوباره تلاش کنید.";

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    // FastAPI puts the message in `detail`; ours are already written in
    // Persian, so they are shown to the user as-is. A validation error comes
    // back as an array instead, which is developer detail, not a sentence.
    if (typeof body?.detail === "string" && body.detail.trim()) return body.detail;
  } catch {
    // Body was not JSON -- fall through to the generic message.
  }
  return SERVER_ERROR_MESSAGE;
}

/** fetch() rejects (rather than resolving with a bad status) when the request
 * never completed at all -- backend down, DNS, CORS, offline. That surfaced
 * as the raw "Failed to fetch"/"NetworkError" string in a red box; this turns
 * it into a sentence a Persian-speaking user can act on. */
async function fetchOrExplain(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error(OFFLINE_MESSAGE);
  }
}

export async function searchListings(payload: UnifiedSearchRequest): Promise<SearchResponse> {
  const response = await fetchOrExplain(`${API_BASE_URL}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

export async function getTransitStations(): Promise<TransitStation[]> {
  const response = await fetch(`${API_BASE_URL}/transit/stations`);
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

export async function getCongestionZones(): Promise<CongestionZone[]> {
  const response = await fetch(`${API_BASE_URL}/transit/congestion-zones`);
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

export async function getNeighborhoods(): Promise<NeighborhoodSummary[]> {
  const response = await fetch(`${API_BASE_URL}/geo/neighborhoods`);
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

/** Polygons for the selected neighborhoods only -- the full set is ~700 KB of
 * GeoJSON, and the map never outlines more than the current selection. */
export async function getNeighborhoodShapes(keys: string[]): Promise<NeighborhoodShape[]> {
  if (keys.length === 0) return [];
  const url = new URL(`${API_BASE_URL}/geo/neighborhoods/shapes`);
  url.searchParams.set("keys", keys.join(","));

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

/** The selected neighborhoods as a single dissolved outline. Where two chosen
 * neighborhoods touch, the border between them is a subdivision of the city,
 * not an edge of the search -- so the server unions them away. */
export async function getSearchArea(keys: string[]): Promise<SearchArea> {
  if (keys.length === 0) return { keys: [], geometry: null };
  const url = new URL(`${API_BASE_URL}/geo/neighborhoods/area`);
  url.searchParams.set("keys", keys.join(","));

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

/** Which محله a map coordinate falls in, or null where the polygons don't
 * reach (parks, highways, unmapped pockets -- about a third of the city). */
export async function getNeighborhoodAt(lat: number, lon: number): Promise<NeighborhoodSummary | null> {
  const url = new URL(`${API_BASE_URL}/geo/neighborhood-at`);
  url.searchParams.set("lat", String(lat));
  url.searchParams.set("lon", String(lon));

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

export async function getCityBoundary(): Promise<CityBoundary> {
  const response = await fetch(`${API_BASE_URL}/geo/city`);
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

export async function getIsochrone(
  lat: number,
  lon: number,
  maxMinutes: number,
  mode: CommuteMode,
): Promise<IsochroneResponse> {
  const url = new URL(`${API_BASE_URL}/transit/isochrone`);
  url.searchParams.set("lat", String(lat));
  url.searchParams.set("lon", String(lon));
  url.searchParams.set("max_minutes", String(maxMinutes));
  url.searchParams.set("mode", mode);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

/**
 * A listing photo, routed through the backend proxy.
 *
 * The raw URLs point at Divar's CDN, which we neither control nor mirror yet.
 * Going through our own origin means one place to add caching and, later, to
 * point at our own object store -- no component that renders an image has to
 * change when that happens.
 */
export function imageUrl(source: string | null | undefined): string | null {
  if (!source) return null;
  return `${API_BASE_URL}/media/image?url=${encodeURIComponent(source)}`;
}

export async function getListing(id: string): Promise<Listing> {
  const response = await fetch(`${API_BASE_URL}/listings/${encodeURIComponent(id)}`);
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  return response.json();
}

/**
 * Streams POST /chat/stream as Server-Sent Events. The backend responds with
 * a StreamingResponse of `data: {...}\n\n` frames -- fetch + ReadableStream is
 * used instead of EventSource because EventSource can't send a POST body.
 */
export async function* streamChat(payload: ChatStreamRequest, signal?: AbortSignal): AsyncGenerator<ChatSSEEvent> {
  const response = await fetchOrExplain(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    throw new Error(await parseErrorDetail(response));
  }
  if (!response.body) {
    throw new Error("Empty response body from chat stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const line = block.trim();
      if (!line.startsWith("data: ")) continue;
      yield JSON.parse(line.slice("data: ".length)) as ChatSSEEvent;
    }
  }
}
