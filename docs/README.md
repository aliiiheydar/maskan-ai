# Documentation

Nine documents. Read them in this order the first time.

| | Document | For |
| :-- | :-- | :-- |
| **۱** | [WHY.md](WHY.md) — فارسی | Why this exists: the gap in Divar, why a ranking is the answer, and why *this* ranking is defensible. Start here — everything else assumes it. |
| **۲** | [GETTING_STARTED.md](GETTING_STARTED.md) | Running it. Development, Docker, production, every environment switch, and the crawl pipeline commands. |
| **۳** | [ARCHITECTURE.md](ARCHITECTURE.md) | The shape of the system: what a search actually does, how storage is split, module boundaries, the map. |
| **۴** | [ALGORITHMS.md](ALGORITHMS.md) | The ranking itself. تبدیل, elastic filter bands, the nine sub-utilities, penalties, Pareto, the trade-off sentence, and how it is made fast. |
| **۵** | [DATA_SCHEMA.md](DATA_SCHEMA.md) | `Listing`, `ExtractedSearchIntent`, and the SQLite tables. |
| **۶** | [CRAWLER.md](CRAWLER.md) | Where the corpus comes from: the two-stage Divar crawler, enrichment, placeholder-price rejection, the geography pipelines. |
| **۷** | [API_SPEC.md](API_SPEC.md) | Every endpoint, with real bodies. |
| **۸** | [FRONTEND_STATE.md](FRONTEND_STATE.md) | The store, the chat⇄filter sync, the map layers, and the design rules that are easy to undo. |
| **۹** | [TESTING_GUIDE.md](TESTING_GUIDE.md) | What is tested, and what the negative cases are protecting. |

## Shortcuts

* **"I just want to run it."** → [GETTING_STARTED.md §1](GETTING_STARTED.md)
* **"Why did this listing rank there?"** → [ALGORITHMS.md §3](ALGORITHMS.md),
  and the `score_breakdown` on every result.
* **"Where did this number come from?"** → [CRAWLER.md](CRAWLER.md), and the
  `provenance` map on every listing.
* **"What does this deployment have switched on?"** → `GET /api/v1/config`,
  documented in [GETTING_STARTED.md §4](GETTING_STARTED.md).

## A note on these documents

Where a document and the code disagree, **the code is right and the document
is a bug**. These describe decisions rather than restating syntax, and the
reasoning behind a particular constant or guard usually lives in a comment
beside it — the docs point at those rather than duplicating them.
