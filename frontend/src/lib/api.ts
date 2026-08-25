import type {
  ChatSSEEvent,
  ChatStreamRequest,
  Listing,
  SearchResponse,
  TransitStation,
  UnifiedSearchRequest,
} from "@/types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function searchListings(payload: UnifiedSearchRequest): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE_URL}/search`, {
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
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
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
