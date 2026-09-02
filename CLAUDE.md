# CLAUDE.md — Maskan AI (Tehran rental discovery)

## Project Overview
A rental search for Tehran that **ranks**. Divar lists the market and orders it
newest-first, because ad position is something it sells; this takes the same
21,377 crawled adverts and answers "of everything that matches, which is the
best answer to what you asked for, and why?". Persian conversational intent
extraction, transit-reachability scoring, and Pareto-optimal ranking sit on top
of that. The reasoning is written up in `docs/WHY.md` (فارسی); the docs index
is `docs/README.md`.

## Core Invariants & Iranian Market Domain Logic
1. **Financial Logic (Tabdil / تبدیل)**:
   - Base Rule: 100,000,000 Tomans Deposit (ودیعه/رهن) ≈ 3,000,000 Tomans Monthly Rent (اجاره).
   - Effective Cost Formula: `C_eff = rent + (deposit * 0.03)`.
   - All financial numbers in code must use **Tomans** (not Rials) as integers (`int64`).
   - تبدیل is **cost-neutral**: it decides feasibility, never price. Apply it in
     the hard mask, never in the price score.
2. **Geospatial Bounds (Tehran)**:
   - Bounding Box: `min_lat: 35.5500, max_lat: 35.8500, min_lon: 51.1000, max_lon: 51.6000`.
   - Public Transit Reference Nodes: Metro Lines 1 to 7, BRT Corridors 1 to 10.
   - Walk Speed: 80 meters/minute (~4.8 km/h).
   - Driving in Congestion Zones: Penalize travel time by 1.4x if crossing into *Tarh-e Terafik*.
   - Reachability is a **weight, not a filter**.
3. **Persian NLP & Character Encoding**:
   - Always normalize Persian characters (convert Arabic 'ي' and 'ك' to 'ی' and 'ک').
   - Clean Persian numbers (`۱۲۳۴۵۶۷۸۹۰` to `1234567890`) before parsing.
   - Every user-facing string, including errors, is Persian. LLM system prompts
     must enforce polite, concise, natural Persian.
4. **Never mutate curated source data.** `crawler/divar_listings.json`,
   `matched_neighborhoods.geojson`, `paired_neighborhoods.json` and
   `tehran_neighborhoods.geojson` are read-only inputs; enrichment writes new
   files.
5. **No user-facing Divar branding.** Images are proxied, never re-hosted.

## The three modes
| Wire value | Label | What it is |
| :-- | :-- | :-- |
| `ranked` | جستجو و رتبه‌بندی | **The product.** Filters + per-criterion importance, ranked by utility. Works with no API key. |
| `chat` | جستجوی گفت‌وگویی (بتا) | The same ranking, driven by a Persian sentence. Needs an OpenRouter key; shown disabled without one. |
| `map` | کاوش نقشه | Unranked viewport filter. Switchable off per deployment; the least important mode. |

Do not rename `فیلتر کلاسیک`/`جستجوی هوشمند` back in: the panel's ranking *is*
the intelligence, and naming it "classic" sold the one thing this app does that
Divar does not as the boring option.

## Tech Stack & External APIs
- **Backend**: Python 3.11+, FastAPI, Pydantic v2, Uvicorn, AsyncIO, NumPy, Shapely, H3, scikit-learn.
- **Database**: SQLite — typed indexed columns + a JSON payload, an R*Tree for the viewport, FTS5 for Persian text, embeddings as float32 blobs. A compressed corpus ships at `backend/app/data/seed/maskan.db.xz` and is unpacked on first start.
- **LLM Backbone**: `~deepseek/deepseek-v4-flash-latest` via OpenRouter (the `~` is part of the id — a floating "latest" alias). **Entirely optional** — with no key the app loses one mode and nothing else.
- **Embeddings**: `openai/text-embedding-3-small` via OpenRouter; local hashing fallback.
- **Frontend**: Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, Zustand, Leaflet + MapLibre GL over OpenFreeMap vector tiles (no API key, no Neshan SDK).
- **Testing**: `pytest`, `pytest-asyncio`, `httpx` (backend), `vitest` (frontend).

## Architectural Rules
1. **Separation of Concerns**:
   - `app/core/`: Domain models, constants, pricing math, Persian normalizers, paths.
   - `app/core/config.py`: everything that comes from the environment — kept apart from `constants.py`, which is domain fact.
   - `app/spatial/`: Transit station graph, routing, distance, isochrones, محله polygons, districts.
   - `app/search/`: Multi-criteria utility ranking, Pareto frontier, map clustering.
   - `app/llm/`: OpenRouter client, prompt templates, streaming.
   - `app/api/v1/`: FastAPI routes, DTOs, SSE.
   - `app/data/pipelines/`: offline builders, never imported by the API.
2. **Output Structure**:
   - `/search` returns **one** `results` list, ordered by utility, floored at
     `MIN_UTILITY_THRESHOLD` (0.45). The old `tier_1_results`/`tier_2_results`
     split was removed — each card carries its own ٪ badge, and a second
     coarser statement of the same fact only put a wall between two listings a
     hundredth of a point apart. Do not reintroduce tiers.
3. **Coding Standards**:
   - Strict typing with Pydantic v2 and Python type hints (`mypy` compliant).
   - Async-first for all network and DB I/O.
   - Zero hardcoded API keys; read from `backend/.env`, which is gitignored.
     Never put a real key in an `.env.example` or any committed file.
   - Comments explain *decisions and measurements*, not syntax. A classifier or
     threshold should be measured against the corpus before it is written in.
4. **UI rules**: no visible scrollbars; the map navigates on click, not hover;
   the ٪ badge is the listing's own score, never stretched across the page.

## Key Commands
- Install Backend: `cd backend && pip install -r requirements.txt`
- Run Backend Dev: `cd backend && uvicorn app.main:app --reload --port 8000`
- Run Backend Tests: `cd backend && pytest -q --tb=short`   (147 tests)
- Install Frontend: `cd frontend && npm install`
- Run Frontend Dev: `cd frontend && npm run dev`
- Run Frontend Tests: `cd frontend && npm test`             (34 tests)
- Typecheck Frontend: `cd frontend && npx tsc --noEmit`
  — **use this, not `npm run build`, while `next dev` is running**; they share
  `.next/` and the build corrupts the dev server's cache.
- Docker (dev): `docker compose -f docker-compose.dev.yml up --build`
- Docker (prod): `docker compose up -d --build`
- Rebuild the corpus: `cd backend && python -m scripts.pipeline`
- Republish the shipped corpus: `cd backend && python -m scripts.pack_seed`

## Housekeeping
- `_archive/` is gitignored and holds superseded notes, scratch files and old
  data dumps. Nothing there is read by any code path.
- Commit and push only when asked.
