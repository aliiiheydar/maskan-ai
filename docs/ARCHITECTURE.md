# System Architecture

Two processes and a file. The FastAPI backend owns the corpus and every
decision made about it; the Next.js frontend owns the interaction. Nothing
else is required to run the product — no database server, no queue, no cache
tier, and no LLM.

---

## 1. The shape of it

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser — Next.js 14 (App Router), React 18, Zustand                    │
│                                                                          │
│   جستجو و رتبه‌بندی      جستجوی گفت‌وگویی (بتا)      کاوش نقشه              │
│   filters + weights      Persian chat              viewport-only         │
│         └────────────────────┴──────────────────────┘                    │
│                    one store (useSearchStore)                            │
│                              │                                           │
│          ┌───────────────────┴────────────────────┐                      │
│          ▼                                        ▼                      │
│   ListingFeed (ranked cards)          Leaflet + MapLibre GL vector map    │
└──────────┬───────────────────────────────────────┬───────────────────────┘
           │  POST /search (JSON)                  │  GET /geo/*, /transit/*
           │  POST /chat/stream (SSE)              │  GET /media/image
           ▼                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  FastAPI  (app/api/v1)                                                   │
│  ┌────────────────────┐   ┌─────────────────────┐  ┌──────────────────┐  │
│  │ app/llm (optional) │   │ app/spatial         │  │ app/core         │  │
│  │ intent extraction  │   │ station graph,      │  │ Tabdil math,     │  │
│  │ Persian dialogue   │   │ routing, isochrone, │  │ Persian          │  │
│  │ embeddings         │   │ محله polygons       │  │ normalisers,     │  │
│  └────────┬───────────┘   └──────────┬──────────┘  │ constants        │  │
│           └──────────────┬───────────┘             └────────┬─────────┘  │
│                          ▼                                  │            │
│              ┌───────────────────────────────────┐          │            │
│              │ app/search — the ranking engine   │◄─────────┘            │
│              │ hard mask → 9 sub-utilities →     │                       │
│              │ one ordered list → Pareto flags   │                       │
│              └──────────────┬────────────────────┘                       │
│                             ▼                                            │
│              ┌───────────────────────────────────┐                       │
│              │ app/data — SQLite + in-memory     │                       │
│              │ repository, offline pipelines     │                       │
│              └───────────────────────────────────┘                       │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                         maskan.db  (21,377 listings; R*Tree + FTS5)
```

---

## 2. What a search actually does

`POST /api/v1/search` is the single endpoint behind all three modes. In order:

1. **Intent.** Panel fields are copied onto an `ExtractedSearchIntent`. In
   `chat` mode the user's sentence is sent to the LLM first and the extracted
   intent is the base the panel fields are laid over — so a filter the user
   set by hand always wins over one the model inferred. Neighborhood *names*
   are resolved to polygon *keys* once, here, and every downstream check runs
   on the keys.
2. **Cache probe.** Ranking is a pure function of (corpus, intent, viewport),
   so it is cached: paging with «بیشتر» is the *same* search asking for rows
   60–90, and panning back to a viewport just left is the same search again.
   Only the head of each ranking is kept (600 rows), so an entry costs a few
   hundred references rather than the whole city.
3. **Narrowing (SQLite).** Every *exact* predicate — the viewport, rooms,
   amenities, the neighborhood keys — is answered from indexes: the R*Tree for
   the rectangle, column indexes for the rest. The inexact parts (تبدیل-adjusted
   budget ceilings, the tolerance band around area) stay in Python and run on
   what survives.
4. **Ranking (memory).** Survivors are hydrated from the in-process cache and
   scored. See [ALGORITHMS.md](ALGORITHMS.md).
5. **Response.** One ordered `results` array, sliced to the requested page,
   plus `total_count` for the whole match set. In `map` mode the response also
   carries `map_points` and `map_clusters`, which together account for *every*
   match in the viewport so the badges add up to the number above the feed.

**Map-explore is deliberately not ranked.** There is no "best" pin when you
are panning a map, so every hard-constraint match is returned unsorted and the
cards hide their ٪ badge in that mode rather than inventing a score.

---

## 3. Storage: SQLite doing two different jobs

The corpus is one file, and the split between what the database does and what
Python does is the main performance decision in the app.

* **`listings`** — one row per property. Every filterable field is a typed,
  indexed column *and* the whole `Listing` is stored as JSON in `payload`. The
  columns let the database narrow without deserialising anything; the document
  means hydration is one `json.loads` and a new optional field needs no
  migration.
* **`listings_geo`** — an R*Tree. "Everything inside this rectangle" is
  map-explore's entire workload and a B-tree on `lat` cannot answer it without
  scanning half the city. Single biggest latency lever here.
* **`listings_fts`** — FTS5 over the Persian title and description, stored
  pre-normalised (Arabic ی/ک folded, Persian digits converted) so a query typed
  either way matches.
* **`embeddings`** — description vectors as float32 blobs in their own table,
  so the common query path never pages 6 KB of vector per row off disk.
* **`fingerprint`** on every row — a hash of the fields that identify a
  *property* rather than an *advert*. Divar reposts the same flat under a
  fresh token when an ad expires; without this the same home appears three
  times in one page.

Connections open in WAL mode with a large page cache and memory-mapped reads.
The corpus is read-almost-only, and WAL means a rebuild in one process does
not block queries in another.

### The seed

`backend/app/data/seed/maskan.db.xz` is the corpus as it ships — 14 MB
compressed, unpacked to `DB_PATH` by `app.main` on the first start that finds
no database. xz because it is the smallest format Python reads with no
dependency at all, and unpacked to a staging file then moved into place, so a
container killed mid-restore leaves nothing behind for the next start to
mistake for a database.

---

## 4. Module boundaries

### Backend (`backend/app/`)

| Module | Owns |
| :-- | :-- |
| `core/` | Domain facts that never come from the environment: Tehran bounds, the تبدیل rate, walk speed, MAUT weights, penalties. Plus the `Listing`/`ExtractedSearchIntent` models, Persian normalisers, and `paths.py` — the one place that knows where files live. |
| `core/config.py` | Everything that *does* come from the environment (`backend/.env`). Kept apart from `constants.py` on purpose. |
| `spatial/` | The 359-node metro/BRT graph (7 metro lines, 10 BRT corridors), leg-by-leg transit routing, isochrone geometry, the 370 محله polygons and the Persian name resolution onto them, the 22 municipal districts, the congestion zones, and a landmark gazetteer. |
| `search/` | The ranking: hard-constraint mask, nine sub-utilities, weight resolution, the Pareto sweep, and the server-side map clustering. |
| `llm/` | The OpenRouter client, Persian intent extraction, dialogue streaming, embeddings. **Every path through here is optional** — with no key the app loses one mode and nothing else. |
| `data/` | `database.py` (SQLite gateway), `repository.py` (the in-process corpus), `price_plausibility.py`, `synthetic_generator.py`, `pipelines/` (offline builders, never imported by the API), `assets/` (the files they read and write), `seed/`. |
| `api/v1/` | Routes, DTOs, dependency injection, SSE. |

### Frontend (`frontend/src/`)

| Module | Owns |
| :-- | :-- |
| `store/useSearchStore.ts` | One Zustand store. Filters, results, map viewport, chat transcript, and the mode. See [FRONTEND_STATE.md](FRONTEND_STATE.md). |
| `components/Filters/` | The panel: ranges, amenity toggles, neighborhood picker, workplace/commute hub, and the per-criterion importance dials. |
| `components/Chat/` | The Persian conversation, streamed token by token, with the extracted intent shown as correctable chips. |
| `components/Map/` | Leaflet container, the MapLibre vector basemap, neighborhood outlines and labels, the search-area overlay, congestion zones, transit stations, workplace picker. |
| `components/Listings/` | Cards, the ranked feed, the detail modal, the gallery. |
| `lib/` | The API client, Persian number/price formatting, and the one match-colour scale shared by pins and badges. |

---

## 5. The map

There is no Neshan SDK and no tile bill. The basemap is a **custom MapLibre
style over OpenStreetMap vector tiles from [OpenFreeMap](https://openfreemap.org)** —
free, no API key, no rate limit — rendered inside a Leaflet container via
`@maplibre/maplibre-gl-leaflet`.

Vector tiles rather than raster are what make this possible at all: colours,
road widths, which features appear at which zoom, and the label *language* are
all decided on the client, so the map could be tuned to look like the quiet,
near-white basemap this product wants instead of being accepted as shipped.
Labels prefer OSM's `name:fa` and fall back to the local name.

Two files have to be self-hosted and are vendored out of `node_modules` at
`pre(dev|build)` time by `frontend/scripts/copy-map-assets.mjs`:

* **the MapLibre worker** — MapLibre locates it relative to `import.meta.url`,
  which webpack rewrites, after which the worker resolves nothing, raises
  nothing, and leaves every tile stuck in "loading" against a blank map;
* **`mapbox-gl-rtl-text`** — loaded into that worker by URL, and required for
  Persian labels to be shaped and ordered correctly.

Above the basemap the map draws, server-fed: listing pins coloured by match
score, counted cluster badges for the dense parts of a viewport, محله outlines
and labels, the dissolved search-area outline, the two congestion zones as
outlined pills, metro/BRT stations past zoom 14, and the commute isochrone as
a single merged outline.

---

## 6. Deployment shape

Two containers, one volume, no orchestration. `docker/backend.Dockerfile` is a
single stage (every dependency is a manylinux wheel — nothing compiles);
`docker/frontend.Dockerfile` is three stages ending in Next.js standalone
output, ~157 MB. Both run as uid 10001. The backend is healthchecked on
`/api/v1/health`, which reports the row count it is *actually* serving —
because a backend that failed to unpack the corpus answers every request
perfectly well and returns the wrong city.

See [GETTING_STARTED.md](GETTING_STARTED.md).
