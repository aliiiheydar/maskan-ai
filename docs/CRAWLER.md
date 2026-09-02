# The Corpus: Crawling and Enrichment

Everything that turns Divar's live site into the 21,377-row database the app
searches. **You do not need to run any of this** — the built corpus ships with
the repository. This is here because the crawl is half the project, and
because refreshing the data means understanding it.

```
crawler/divar-crawler.py            divar_listings.json   (raw, read-only)
        │  discovery + detail              │
        ▼                                  ▼
  app/data/pipelines/divar_preprocess.py   processed_listings.json
        │  normalise · mine text · classify · locate
        ▼
  scripts/build_database.py                maskan.db
        │  fingerprint · index · purge
        ▼
  scripts/build_neighborhood_quality.py    neighborhood_quality.json
```

All four stages run as one resumable command:

```bash
cd backend && python -m scripts.pipeline
```

---

## 1. Crawling

Two stages, deliberately using two different mechanisms.

### Discovery — a headless browser, because the feed is virtualised

Divar's post list only ever holds ~10–16 anchors in the DOM no matter how far
you scroll, and its `POST /v8/postlist/w/search` endpoint pages through opaque
server-issued state: a `search_uid`, a base64 `viewed_tokens` blob and an ISO
`last_post_date`. Reconstructing that by hand is a losing game against a
moving target, so the crawler drives the real site in Chromium, scrolls the
feed's inner scroll container, and reads post tokens out of the search
responses **the page itself makes**.

### Sharding, because one stream caps out

A single result stream runs dry at ~220 posts. Discovery is therefore sharded
across Tehran's ~450 district slugs, visited in random order — so the crawl
**samples** the city rather than draining all ~150,000 listings from wherever
it started.

Each shard's quota is **proportional to how dense its market actually is**. A
probe pass measures each shard's posting rate and the target is divided out in
proportion, so ونک contributes far more of the sample than a quiet outlying
slug. Without this, a uniform quota over-samples thin districts and produces a
corpus that does not look like Tehran. The measurement is cached in
`district_density.json` and reused until it goes stale.

### Detail — plain HTTP, because a browser would be waste

`GET /v8/posts-v2/web/<token>` returns the whole widget tree as JSON and needs
no browser at all. Spending a page load per listing would be pure cost.

### Resumability

Both stages checkpoint to disk after every write: tokens seen
(`discovered_tokens.json`) and posts already fetched (`crawled_tokens.json`).
A city-wide crawl runs for hours; it has to survive being interrupted.

```bash
python3 crawler/divar-crawler.py --target 3000   # smaller sample, same spread
python3 crawler/divar-crawler.py --stage detail  # drain the existing queue only
python3 crawler/divar-crawler.py --probe         # re-measure density first
python3 crawler/divar-crawler.py --seed 42       # reproduce a previous sample
```

**`crawler/divar_listings.json` is opened read-only and never written back.**
Enrichment produces a *new* file. A source you have spent hours collecting
should not be mutable by a pipeline you are still changing.

---

## 2. Enrichment — `app/data/pipelines/divar_preprocess.py`

The crawl is a mixture of two very different kinds of evidence, and keeping
them apart is the whole point of this stage:

* **Reliable fields** — what Divar itself stored as typed data: the deposit,
  the rent, the area, the مشخصات attribute table, the geo point. Taken as-is.
* **Text fields** — the title and the free-form Persian description, where the
  advertiser says everything Divar never asked them for. Mined only to **fill
  holes**, never to overwrite a reliable value.

Every listing carries a `provenance` map saying, per field, which of the two a
value came from — so the detail page can present a text-derived «۲ خوابه»
differently from one Divar itself recorded, the same way Divar separates its
own attribute table from the ad copy.

### Persian normalisation

Arabic ي/ك folded to ی/ک, ة to ه, Persian digits ۱۲۳ to 123, zero-width
joiners collapsed. Applied before *every* match and stored pre-normalised for
the full-text index, so a query typed either way finds the same rows.

### Placeholder prices

A widespread habit in this market: rather than publish a price, the advertiser
types a token figure — ودیعه ۱٬۰۰۰ تومان — so anyone interested has to phone
and ask. The listing is real; its price is not.

Left in, these are corrosive out of all proportion to their number, because
**every one of them looks like the cheapest home in Tehran**: they win the
budget criterion outright and sit at the very top of the ranking.

Divar has no flag for them, so they are recognised by the only thing that
gives them away — a price no real Tehran lease could carry. Two independent
floors, either sufficient:

| Floor | Value | Evidence |
| :-- | --: | :-- |
| Tabdil-normalised monthly cost | 1,000,000 تومان | The corpus has 41 ads below it, then a clean gap: the 0.5th percentile is 103,000 and the 1st is 1,650,000 |
| Cost per m² | 35,000 تومان/m² | Catches the other shape of the trick — a plausible اجاره ۱۰٬۰۰۰٬۰۰۰ on a 400-متر penthouse |

Both sit an order of magnitude under the cheapest genuine listing, so they
cost real inventory nothing. A third check runs at store time against the
*local* price level, cell by cell, catching ads priced far below their own
surroundings.

### What is not a home

Divar files rooms, dormitory beds, flatmate slots and **parking spaces let on
their own** under the same `apartment-rent` category as apartments. They quote
a fraction of a whole-unit price, so mixed into the results they dominate the
cheap tail of every search and make an ordinary rental look overpriced.
`app/core/shared_living.py` classifies them into their own market
(هم‌خانه و خوابگاه).

The parking rule is the interesting one, because پارکینگ by itself means
nothing: 1,534 of 21,377 titles carry the word and nearly all are flats
advertising the spot they come with. What is matched is پارکینگ as the
**subject** of the advert — a letting verb running into it, the title opening
on it, the reverse order, or a title that is nothing but the word — and never
as one of its listed features. A dwelling guard (خواب، آپارتمان، طبقه، متری…)
overrides all of it.

The asymmetry of the errors is what sets the tuning: a home wrongly filed as
parking **disappears from the search it belongs in**, while parking wrongly
left in merely looks cheap. So the guards stay conservative, and every
candidate pattern was measured over all 21,377 stored adverts — with every new
match and every dropped one read by hand — before being written into the
module.

### Locating a listing

Each listing is assigned an H3 resolution-8 cell, its nearest metro/BRT node
and walk time (metres ÷ 80), its congestion-zone flags, its municipal district
by polygon containment, and its محله — by containment first, with a nearest
representative point as fallback.

---

## 3. Storing — `scripts/build_database.py`

Rows, indexes, the R*Tree, the FTS index, fingerprints. See
[DATA_SCHEMA.md §3](DATA_SCHEMA.md).

The pipeline's default is a **merge**, not a rebuild: a run adds what is new
and refreshes what changed rather than discarding a corpus that took hours to
collect. `--rebuild` is the explicit way to say "this crawl replaces the old
one".

Duplicates are handled at the stage where each kind is visible — the crawler
skips tokens it has already fetched; the store skips *reposts* (the same
property re-advertised under a fresh token) by fingerprint, while still
updating a row whose own token comes round again.

---

## 4. The geography, built once

These are separate pipelines because their sources change on the scale of
years, not hours.

### محله polygons — 370 of them

Two curated sources joined on a shared `key`: `matched_neighborhoods.geojson`
(one polygon each) and `paired_neighborhoods.json` (title/subtitle/keywords as
a listings portal shows them). That pairing covers **258** neighborhoods.

`search_keywords` is what makes conversational and free-text search work at
all: it lists the streets and landmarks people actually name when they mean a
neighborhood — «سئول، فجر، ونک…» for آرارات — which is rarely the
neighborhood's own title. Resolution matches titles *and* keywords, and always
returns the stable key.

### Filling the gaps — `build_gap_neighborhoods.py`

Those 258 left about a third of the city inside no neighborhood at all: a
click there resolved to nothing, and a search for the area's own name found
nothing. Most of that hole was not unmapped — 107 named polygons in
`tehran_neighborhoods.geojson` simply never matched a key, and they account
for 193 of the 204 uncovered km².

So: those polygons (plus whatever sizeable land is *still* outside everything)
are cut into pieces big enough to be a neighborhood and thick enough not to be
a road corridor, then **named from OpenStreetMap** — each polygon is handed to
Overpass as a `poly:` filter and the named streets, transit stops, parks and
civic landmarks inside it come back as its `search_keywords`, in the same
comma-separated shape the portal's own subtitles use. Four of the curated
polygons are literally named "Unknown"; what makes them findable is the
keywords, not the title.

Nothing is written back to a source. The result lands in
`gap_neighborhoods.geojson` and is merged in at load time, so the curated
files stay exactly as received and the generated coverage can be rebuilt or
dropped on its own. A key defined in both wins from the curated file. Overpass
answers are cached, so a re-run costs no requests.

### Transit — `scripts/build_transit_data.py`

359 nodes from raw scraped sources: 150 metro stations across lines 1–7 and
209 BRT stops across corridors 1–10, with interchange relations. This is what
`app/spatial/routing.py` routes over leg by leg — replacing an earlier model
that divided a straight line by an average network speed and could not tell a
direct trip from one with two interchanges.

### Neighborhood quality — `scripts/build_neighborhood_quality.py`

A 0..1 desirability index per محله, from two components:

* **prestige** — price level per m², shrunk toward the municipal district's
  published market figure so a محله with six listings is not ranked off six
  listings. Price is the only signal that aggregates everything people mean by
  "a good area" — schools, air, safety, shops, green space — into one number
  the market has already agreed on.
* **modernity** — median building age, which separates a district of 1970s
  walk-ups from one of serviced towers at the same price.

Precomputed for the same reason the market baselines are: it is a corpus-wide
aggregate, and recomputing it inside the scoring loop would dominate the
search. A neighborhood with no entry scores the neutral 0.5 — never penalised
for our missing data.

---

## 5. Publishing a refreshed corpus

```bash
python -m scripts.pack_seed
```

Checkpoints the WAL into the main file (the seed is one file — anything still
in `maskan.db-wal` would simply be missing from the copy everyone else
receives), VACUUMs, and writes `app/data/seed/maskan.db.xz` at xz preset
9-extreme: 114 MB → 14 MB in about a minute. That minute is bought back on the
first `git clone`.

---

## 6. Ethics and limits

* Listing data is crawled for research purposes at a deliberately modest rate,
  sampled rather than drained.
* No Divar branding appears anywhere in the product.
* Images are **proxied, never re-hosted** — we hold the CDN URLs and none of
  the files.
* The corpus is a snapshot of what was advertised at crawl time. It does not
  know which listings have since been let.
