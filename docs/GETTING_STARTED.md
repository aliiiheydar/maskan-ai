# Getting Started

Three ways to run this, in the order you will probably want them: the two
servers on your own machine (fastest edit-run loop), the same thing in
containers (nothing to install), and a production deployment.

Every route ends up with the same corpus. **You never need to crawl Divar to
run this project** — a compressed copy of the 21,377-listing database ships in
the repository at `backend/app/data/seed/maskan.db.xz` (14 MB) and the backend
unpacks it the first time it starts and finds no database.

---

## 1. Development, on your machine

**Requires** Python 3.11+ and Node 20+.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # works as-is; see §4 to enable the chat
uvicorn app.main:app --reload --port 8000
```

The first start prints one of three lines, and which one you get is worth
reading:

```
[maskan] unpacked the shipped corpus to .../maskan.db   ← first run, expected
[maskan] loaded 21377 listings from maskan.db           ← every run after
[maskan] no database found; falling back to the synthetic corpus
```

The third means the seed was missing (a partial checkout, or `git-lfs` not
pulled) and you are searching 3,000 invented listings. `GET
/api/v1/health` reports the row count for exactly this reason.

```bash
# Frontend, in a second terminal
cd frontend
npm install
cp .env.example .env
npm run dev                               # http://localhost:3000
```

`npm run dev` runs `scripts/copy-map-assets.mjs` first, which vendors the
MapLibre worker and the Vazirmatn font files out of `node_modules` into
`public/`. Both have to be loaded by URL rather than through the bundler — see
the comments in that script.

### Tests

```bash
cd backend && pytest -q            # 147 tests
cd frontend && npm test            # 34 tests
cd frontend && npx tsc --noEmit    # typecheck
```

Do not run `npm run build` while `next dev` is running — the two share
`.next/` and the build corrupts the dev server's cache. `npx tsc --noEmit` is
the check you want during development.

---

## 2. Development, in containers

For a machine you would rather not install Python 3.11 and Node 20 on. Source
is mounted from the host and both servers reload on save.

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose -f docker-compose.dev.yml up --build
```

Frontend on `:3000`, backend on `:8000`, the corpus on a named volume
(`maskan-db-dev`) so it survives rebuilds. It is slower than §1 — file
watching across a bind mount always is — but it needs nothing on the host but
Docker.

---

## 3. Production

```bash
cp backend/.env.production.example backend/.env.production
$EDITOR backend/.env.production          # CORS_ALLOW_ORIGINS is the one you must change
docker compose up -d --build
```

Two images and one volume:

| Service | Image | Notes |
| :-- | :-- | :-- |
| `backend` | `python:3.11-slim`, ~500 MB | Runs as uid 10001, healthchecked on `/api/v1/health` |
| `frontend` | Next.js standalone on `node:20-alpine`, ~157 MB | Runs as uid 10001, serves the traced build |
| `maskan-db` | volume | Where the corpus is unpacked; survives `up --build` |

`docker compose up` waits for the backend to report healthy before starting
the frontend, because the backend's first start unpacks 114 MB of SQLite.

### The one thing that is not a runtime setting

`NEXT_PUBLIC_API_BASE_URL` is compiled into the JavaScript bundle, because the
**browser** reads it and the browser never sees the container's environment.
It is a build argument:

```bash
NEXT_PUBLIC_API_BASE_URL=https://api.example.com/api/v1 docker compose build frontend
docker compose up -d frontend
```

Two consequences worth stating plainly. It must be an address the *user's*
machine can resolve — `http://backend:8000` works between containers and will
never work here. And changing it means rebuilding the image; there is no
runtime knob, and pretending there was one would ship a frontend that quietly
calls `localhost` from someone else's laptop.

### Behind a reverse proxy

Terminate TLS at your proxy, route `/` to `frontend:3000` and your API
hostname to `backend:8000`, and set `CORS_ALLOW_ORIGINS` to the origin the
frontend is actually served from. A wrong value there fails as CORS errors in
the browser while the API itself answers every request perfectly — it is the
single most common way to get a blank result panel.

---

## 4. Every switch

### `backend/.env` — read by `app/core/config.py`

| Variable | Default | What it does |
| :-- | :-- | :-- |
| `OPENROUTER_API_KEY` | placeholder | **The only optional feature in the app.** With a real key, جستجوی گفت‌وگویی works: Persian chat replies and intent extraction. Without one, `GET /config` reports the mode unavailable and the header shows it disabled. Nothing else changes — the ranking, the scores and the map are computed locally and are byte-identical either way. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint. |
| `LLM_MODEL` | `deepseek/deepseek-chat` | Chat and intent extraction. |
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Description vectors. Only the corpus builders use these; with no key they fall back to a local hashing vectoriser. |
| `DB_PATH` | *(empty)* | Where the SQLite corpus lives. Empty means inside the package (`app/data/assets/maskan.db`). The compose files set it to `/data/maskan.db` on a mounted volume. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated origins allowed to call the API. |
| `EXPLORE_MAP_ENABLED` | `True` | کاوش نقشه, the free-roam map mode. `False` and the header drops the mode entirely — the map panel itself stays. Hidden rather than disabled, because nothing is missing from the server: the mode is simply not part of the product on this deployment. |
| `DEFAULT_LAT` / `DEFAULT_LON` | `35.6997` / `51.3380` | Where the map opens. |
| `APP_ENV` / `DEBUG` | `development` / `True` | |

The two capabilities are published at `GET /api/v1/config` and read once by
the frontend at startup, because which modes exist is a fact about the
deployment and the client has no other way to find out.

### `frontend/.env` — read by Next.js

| Variable | Default | What it does |
| :-- | :-- | :-- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | Where the browser reaches the API. Compiled into the bundle; see §3. |

There is no server-side secret in the frontend. Everything it knows, it asks
the backend for.

---

## 5. Rebuilding the corpus

You only need this to *refresh* the data — the shipped seed is a complete,
working corpus. The full path from Divar to a searchable database is one
resumable command:

```bash
cd backend
python -m scripts.pipeline                  # crawl → enrich → store → quality index
```

| Flag | Effect |
| :-- | :-- |
| `--target 3000` | Sample 3,000 listings instead of 10,000, with the same city-wide spread |
| `--districts 40` | Discovery limited to 40 district shards |
| `--probe` | Re-measure each district's posting density before allocating quotas |
| `--uniform` | Equal quota per district instead of density-weighted |
| `--skip-crawl` | Re-enrich and re-store the crawl already on disk |
| `--rebuild` | Replace the corpus rather than merging into it |
| `--embed` | Also backfill description vectors (slow, and billed to OpenRouter) |

The default is a **merge**, not a rebuild: a run adds what is new and
refreshes what changed, without discarding a corpus that took hours to
collect. Duplicates are handled where each kind is visible — the crawler skips
tokens it has already fetched, and the store skips *reposts* (the same
property re-advertised under a fresh token) by fingerprint.

Then, if the new corpus is the one other people should get:

```bash
python -m scripts.pack_seed                 # ~1 min; rewrites the 14 MB seed file
```

This is deliberately a separate command rather than a pipeline stage: a
nightly merge should not rewrite a tracked binary.

What each stage does, and why the crawler is built the way it is:
**[CRAWLER.md](CRAWLER.md)**.

### The other builders

These run on their own, rarely, when their source data changes:

```bash
python -m scripts.build_transit_data          # metro/BRT graph from the raw scrapes
python -m scripts.build_neighborhood_quality  # the 0..1 محله desirability index
python -m scripts.build_database              # store only, from an existing enrichment
python -m app.data.pipelines.match_neighborhoods    # محله polygons ↔ Divar keys
python -m app.data.pipelines.build_gap_neighborhoods
```

---

## 6. Troubleshooting

| Symptom | Cause |
| :-- | :-- |
| `no database found; falling back to the synthetic corpus` | The seed file is missing. `GET /api/v1/health` will report ~3,000 listings instead of 21,377. |
| Empty result panel, API answers fine in `curl` | `CORS_ALLOW_ORIGINS` does not list the origin the browser loaded the frontend from. |
| Frontend calls `localhost:8000` from another machine | `NEXT_PUBLIC_API_BASE_URL` was not set **at build time**. |
| جستجوی گفت‌وگویی shown as غیرفعال | No `OPENROUTER_API_KEY`. Everything else works. |
| Blank map, tiles stuck loading | `public/vendor/maplibre/` is missing — run `npm run dev`/`npm run build`, which vendor it, rather than `next dev` directly. |
| `env file backend/.env.production not found` | Copy it from `.env.production.example`; compose requires it rather than starting misconfigured. |
