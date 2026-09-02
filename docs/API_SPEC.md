# REST & Streaming API

Base URL: `http://localhost:8000/api/v1`. Interactive docs at
`http://localhost:8000/docs` (FastAPI generates them from the same models).

Every user-facing error message is Persian, because it is shown to the user
verbatim.

| | Endpoint | |
| :-- | :-- | :-- |
| `POST` | `/search` | The one search endpoint, for all three modes |
| `POST` | `/chat/stream` | Persian conversation, SSE |
| `GET` | `/listings/{id}` | One listing in full |
| `GET` | `/geo/neighborhoods` | All 370 محله, without polygons |
| `GET` | `/geo/neighborhoods/shapes` | Polygons, for selected keys only |
| `GET` | `/geo/neighborhoods/area` | The selection dissolved into one outline |
| `GET` | `/geo/neighborhood-at` | Which محله contains a point |
| `GET` | `/geo/city` | Tehran's municipal boundary |
| `GET` | `/transit/stations` | Metro and BRT nodes |
| `GET` | `/transit/congestion-zones` | طرح ترافیک / طرح آلودگی boundaries |
| `GET` | `/transit/isochrone` | Commute reachability geometry |
| `GET` | `/media/image` | Read-through proxy for listing photos |
| `GET` | `/config` | What this deployment can do |
| `GET` | `/health` | Liveness plus the row count actually being served |

---

## `POST /search`

One endpoint behind all three modes; `mode` decides which.

| `mode` | Meaning |
| :-- | :-- |
| `ranked` | **The default.** Filters, weighted into one utility score per listing, ordered by it. |
| `chat` | The same ranking with `query_text` extracted into filters by the LLM first. Requires an OpenRouter key — `503` with a Persian message without one. |
| `map` | Unranked viewport filter. Returns every match in `bbox` as pins and counted cells; the panel's filters are deliberately **not** applied. |

### Request

Every field is optional except `mode` (which defaults to `ranked`).

```json
{
  "mode": "ranked",
  "query_text": null,
  "neighborhoods": ["یوسف‌آباد"],
  "min_deposit_toman": null,
  "max_deposit_toman": 800000000,
  "min_rent_toman": null,
  "max_rent_toman": 30000000,
  "min_area_sqm": 70,
  "max_area_sqm": null,
  "rooms": 2,
  "min_floor": null,
  "max_floor": null,
  "min_build_year": null,
  "requires_elevator": true,
  "requires_parking": false,
  "requires_storage": false,
  "requires_balcony": false,
  "requires_images": false,
  "full_rahn_only": false,
  "convertible_only": false,
  "living_kind": "standard",
  "financial_persona": "balanced",
  "criteria_importance": { "budget": "high", "metro": "low" },
  "workplace_lat": 35.7022,
  "workplace_lon": 51.3533,
  "max_commute_mins": 40,
  "commute_mode": "transit",
  "commute_importance": 0.5,
  "bbox": { "min_lat": 35.68, "min_lon": 51.35, "max_lat": 35.75, "max_lon": 51.45 },
  "map_zoom": 14,
  "page": 1,
  "page_size": 60,
  "offset": 0
}
```

Notes on the fields that are not self-evident:

* **`neighborhoods`** takes polygon keys from `/geo/neighborhoods`, but
  Persian titles are accepted too and resolved server-side — a hand-written
  request works.
* **`bbox` and `neighborhoods` are alternatives, never a conjunction.** A
  viewport intersected with a محله the user cannot see would silently return
  nothing and look like a broken filter.
* **`living_kind`** — `standard` is whole homes; `shared` returns *only*
  rooms, dormitory beds, flatmate slots and parking spaces let on their own.
  Never both: per-person prices are not comparable with whole-unit prices, so
  ranking them against each other is meaningless.
* **`criteria_importance`** — `low` / `normal` / `high` per criterion, mapping
  to ×0.4 / ×1.0 / ×2.2 on the documented default weights.
* **`offset`** wins over page arithmetic when sent, because only the client
  knows where its own list ends. The first page is larger than the rest, so an
  offset computed from the page number re-serves rows the feed already has.
* **`map_zoom`** decides how much of a viewport comes back as individual pins
  rather than counted badges, so it travels with the box that defines them.

### Response

One ordered list. Trimmed to a single result; the تبدیل is real and worth
reading — the advertiser wanted ۱٫۶ میلیارد رهن کامل, and the engine found the
point on that listing's conversion line that fits an ۸۰۰ میلیون ceiling.

```json
{
  "natural_language_summary": "۴ مورد یافت شد.",
  "results": [
    {
      "id": "divar-gaEGm5p6",
      "title": "ابن سینا  85 متر  با آسانسور ( مناسب مجردی )",
      "neighborhood": "یوسف‌آباد",
      "neighborhood_key": "90",
      "district": "منطقه ۶",
      "deposit_toman": 1600000000,
      "rent_toman": 0,
      "area_sqm": 85,
      "rooms": 2,
      "floor": 3,
      "total_floors": 3,
      "build_year": 1377,
      "has_elevator": true,
      "has_parking": false,
      "has_storage": false,
      "has_balcony": true,
      "can_convert": true,
      "is_full_rahn": true,
      "image_count": 6,
      "thumbnail_url": "https://postimage01.divarcdn.com/.../e3845168.webp",
      "source_url": "https://divar.ir/v/gaEGm5p6",
      "suggested_deposit_toman": 800000000,
      "suggested_rent_toman": 24000000,
      "lat": 35.728569727274,
      "lon": 51.412176607741,
      "dist_to_metro_mins": 6.6005612225,
      "commute_to_work_mins": null,
      "utility_score": 0.822,
      "trade_off_rationale": null,
      "is_pareto_optimal": true,
      "score_breakdown": {
        "budget": 0.822, "value": 1.0,     "area": 1.0,
        "amenity": 1.0,  "metro": 0.587,   "commute": 1.0,
        "quality": 0.732,"freshness": 0.155,"soft": 1.0
      }
    }
  ],
  "map_points": [],
  "map_clusters": [],
  "total_count": 4,
  "applied_intent": { "max_deposit": 800000000, "must_have_elevator": true, "target_neighborhood_keys": ["90"], "…": "…" }
}
```

| Field | Meaning |
| :-- | :-- |
| `results` | **One page of the ranking, strongest match first.** Not two tiers — see [ALGORITHMS.md §6](ALGORITHMS.md). |
| `total_count` | The full match count, not the page's. |
| `utility_score` | 0..1, the number the card prints as a ٪ badge and the key the list is sorted by. Never below 0.45 in a ranked mode; always 0 in `map` mode, where nothing is ranked. |
| `suggested_*_toman` | The (deposit, rent) split the engine had to assume for this listing to fit the budget. Present **only** when it differs from the advertised one, so the UI can say «با تبدیل» rather than silently showing a price the advertiser never published. |
| `is_pareto_optimal` | Nothing else in the whole search beats it on cost, metro walk and area at once. |
| `trade_off_rationale` | The Persian sentence explaining what a lower-ranked result offers in exchange. `null` unless earned. |
| `score_breakdown` | The nine sub-utilities behind `utility_score`, so the UI can *explain* a match rather than only assert a percentage. |
| `applied_intent` | What the search actually ran with, after extraction and neighborhood resolution — reflected back into the panel so an inferred filter is visible and correctable. |
| `map_points` / `map_clusters` | `map` mode only. Together they account for **every** match in the viewport, so the badge counts add up to the number above the feed. |

---

## `POST /chat/stream`

`text/event-stream`. Requires an OpenRouter key; `503` with a Persian message
without one.

```json
{
  "message": "یه خونه نزدیک مترو شادمان می‌خوام آسانسور داشته باشه ودیعه تا ۳۰۰ تومن",
  "history": [
    { "role": "user", "content": "سلام" },
    { "role": "assistant", "content": "سلام! چه منطقه‌ای از تهران مدنظرتان است؟" }
  ]
}
```

```
data: {"event":"token","content":"در"}
data: {"event":"token","content":" نزدیکی"}
data: {"event":"token","content":" مترو شادمان..."}
data: {"event":"state_update","extracted_intent":{"max_deposit":3000000000,"must_have_elevator":true,"target_neighborhoods":["شادمان"],"target_neighborhood_keys":["146"]}}
data: {"event":"done"}
```

Three frame types: `token`, one `state_update` carrying the extracted intent,
and `done`.

**Failures arrive as an `error` frame followed by `done`, never as a torn
connection.** An aborted SSE body reaches the browser as an opaque "network
error", which tells the user nothing and leaves the assistant bubble spinning
forever. If the reply streamed but extraction failed, the turn still ends
normally with nothing applied — a good answer is not thrown away because the
filters could not be read out of it.

`extracted_intent` is serialised with `exclude_unset`, so an absent field
means *the user did not mention this*, never *clear it*.

---

## `GET /listings/{id}`

The full `Listing` (see [DATA_SCHEMA.md](DATA_SCHEMA.md)), including the
description, the image list and the per-field `provenance` map. `404` with a
Persian message when the id is unknown.

Used for the detail view, and by the map: map-explore plots the whole viewport
but pages the feed 30 at a time, so most pins have no card loaded — the one
that is clicked is fetched on its own.

---

## `GET /geo/*`

| Endpoint | Query | Returns |
| :-- | :-- | :-- |
| `/geo/neighborhoods` | — | Every محله as `{key, title, subtitle, center_lat/lon, min/max bounds, area_sqkm}` — **no polygons**, which is ~250× smaller than shipping every outline to every client on load |
| `/geo/neighborhoods/shapes` | `keys=90,146` | `{key, title, geometry}` for the selected keys only |
| `/geo/neighborhoods/area` | `keys=90,146` | The selection **dissolved into one outline**. Where two chosen محله touch, the border between them is an artefact of how the city is subdivided, not a boundary of the search — and unioning server-side avoids shipping a polygon-clipping library to every browser |
| `/geo/neighborhood-at` | `lat`, `lon` | The محله containing that point, or `null` |
| `/geo/city` | — | Tehran's municipal boundary (OSM relation 6663864) |

`area_sqkm` exists because the client sizes its behaviour to the area being
searched, and a bounding box overstates an irregular shape by half.

## `GET /transit/*`

| Endpoint | Query | Returns |
| :-- | :-- | :-- |
| `/transit/stations` | — | 359 nodes: 150 metro across lines 1–7, 209 BRT across corridors 1–10, with `{id, name, name_en, lat, lon, type, lines}` |
| `/transit/congestion-zones` | — | `[{zone, label, geometry}]` for `tarh_terafik` and `tarh_aloodegi` |
| `/transit/isochrone` | `lat`, `lon`, `minutes`, `mode` | `{mode, geometry}` — one merged GeoJSON polygon of what is reachable, not a scatter of circles |

## `GET /media/image`

`?url=` a `https://*.divarcdn.com` image. A narrow read-through proxy: we hold
the CDN URLs but none of the images, and re-hosting six thousand listings'
photos would mean tens of thousands of requests against a rate-limited origin.
Non-matching URLs are rejected (`400`); oversized or non-image responses are
rejected (`415`).

## `GET /config`

```json
{ "ai_search_enabled": true, "explore_map_enabled": true }
```

Which modes exist is a property of the deployment and the client has no other
way to find out. Without this the frontend would offer جستجوی گفت‌وگویی, let
the user type a sentence, and answer with a 503.

The two are missing for different reasons, and the UI treats them differently:
the conversational mode needs a key someone forgot, so it is shown **disabled**
(hiding it would read as a feature that was never built); the explore map is a
switch someone threw, so it is **hidden** (there is nothing here for the user
to go and fix).

## `GET /health`

```json
{ "status": "ok", "listings": 21377 }
```

Both facts, because "up" alone is not the question anyone is asking. A backend
that came up on the 3,000-listing synthetic fallback — an unpacked seed that
failed, a volume that did not mount — answers every request perfectly well and
returns the wrong city. The Docker healthcheck and a human `curl` read the
same line.
