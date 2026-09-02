# مسکن‌یار — Maskan AI

**A rental search for Tehran that ranks.**

Divar lists Tehran's rental market; it does not order it. Filters narrow the
pile and then the pile arrives newest-first, because the position of an advert
in that list is something the platform sells. This project takes the same
market — 21,377 real adverts, crawled — and answers a different question: *of
everything that matches, which homes are the best answer to what you asked
for, and why?*

Every result carries a match score, the list is sorted by it, and the card can
tell you what a lower-ranked home is offering in exchange for its position
("۲۵ متر بزرگ‌تر است، اما ۱۰٪ بالاتر از بودجهٔ شماست").

> The reasoning behind the product — the gap in Divar, why a ranking is the
> answer, and why *this* ranking is defensible — is written up in Persian in
> [docs/WHY.md](docs/WHY.md).

---

## What is in here

| | |
| :-- | :-- |
| **Corpus** | 21,377 Tehran rental adverts crawled from Divar, normalised into a typed corpus with provenance per field |
| **Ranking** | Multi-Attribute Utility Theory over nine sub-utilities, with تبدیل-aware budgeting and elastic filter bands |
| **Geography** | 370 محله polygons, 359 metro/BRT nodes (7 lines, 10 corridors), the 22 municipal districts, and the two congestion zones |
| **Map** | A custom Divar-like vector basemap, built on OpenStreetMap through OpenFreeMap — no API key, no tile bill |
| **Persian** | Normalisation, digit handling and RTL throughout; every user-facing string is Persian |
| **Conversation** | An optional LLM layer that turns a Persian sentence into the same filters the panel sets — and is entirely optional |

## Three ways to search

* **جستجو و رتبه‌بندی** — the product. Filters plus per-criterion importance
  dials, ranked by utility. Works with no API key and no network beyond the
  map tiles.
* **جستجوی گفت‌وگویی** (بتا) — say it in Persian; an LLM extracts the same
  filters, which stay visible and correctable in the panel. Needs an
  OpenRouter key; without one the mode is shown disabled and nothing else
  changes.
* **کاوش نقشه** — pan and zoom; every listing in the viewport, unranked.
  Switchable off per deployment.

## Run it

```bash
git clone <this repo> && cd maskan-ai
cp backend/.env.production.example backend/.env.production
docker compose up -d --build          # http://localhost:3000
```

The corpus ships with the repository as a 14 MB compressed SQLite file and is
unpacked on first start — **nobody has to re-crawl Divar to run this.**

Running the two servers directly, the crawler pipeline, and every environment
switch: **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**.

## Documentation

| Document | What it covers |
| :-- | :-- |
| [docs/WHY.md](docs/WHY.md) | فارسی — the problem, the gap in Divar, and why this ranking is right |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | Running it: development, Docker, production, every env switch, the crawl pipeline |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, boundaries, request flow, and the map |
| [docs/ALGORITHMS.md](docs/ALGORITHMS.md) | The ranking: تبدیل, elastic bands, the nine sub-utilities, Pareto |
| [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) | The `Listing` entity, the intent schema, the SQLite schema |
| [docs/CRAWLER.md](docs/CRAWLER.md) | The crawler and every offline pipeline that turns a scrape into the corpus |
| [docs/API_SPEC.md](docs/API_SPEC.md) | Every endpoint, with real request and response bodies |
| [docs/FRONTEND_STATE.md](docs/FRONTEND_STATE.md) | The Zustand store, the chat↔filter sync, the map layers |
| [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) | What is tested and how to run it |

## Stack

**Backend** — Python 3.11, FastAPI, Pydantic v2, SQLite (R*Tree + FTS5),
NumPy, Shapely, H3.
**Frontend** — Next.js 14 (App Router), React 18, TypeScript, Tailwind,
Zustand, Leaflet + MapLibre GL.
**LLM (optional)** — DeepSeek via OpenRouter for Persian dialogue and intent
extraction.

## Built with Claude Code

This codebase was written with [Claude Code](https://claude.com/claude-code)
as a working partner rather than an autocomplete, and the way it was used is
visible in the result:

* **The comments explain decisions, not syntax.** Almost every non-obvious
  constant and guard in this repository carries the measurement or the failure
  that produced it — why the parking classifier requires the noun to be the
  advert's subject, why the Pareto sweep replaced the pairwise comparison, why
  the trade-off sentence is silent rather than one-sided. That record is the
  most valuable thing in the codebase and it exists because it was written
  while the reasoning was still fresh.
* **Rules were measured against the corpus before being adopted.** Persian
  text classifiers here were not guessed: candidate patterns were run over all
  21,377 stored adverts and every new match and every dropped one inspected by
  hand before the pattern was written into a module.
* **The parts nobody enjoys writing got written.** 147 backend tests and 34
  frontend tests, the offline pipelines, the neighborhood gap-filling, the
  eval harness for intent extraction.

The project instructions that steer that collaboration are in
[CLAUDE.md](CLAUDE.md) — the domain invariants (تبدیل rate, Tehran bounds,
Persian normalisation) live there so that no session can quietly contradict
them.

## Data and attribution

Listing data is crawled from Divar for research purposes; no Divar branding is
used in the product and listing images are proxied rather than re-hosted.
Basemap tiles are © OpenStreetMap contributors via
[OpenFreeMap](https://openfreemap.org). Geocoding of workplace addresses uses
OpenStreetMap Nominatim on explicit user submit only.
