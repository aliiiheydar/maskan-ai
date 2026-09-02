# Data Schema

Three shapes matter: the `Listing` the app ranks, the `ExtractedSearchIntent`
a query resolves to, and the SQLite tables underneath. How a listing *becomes*
one of these is [CRAWLER.md](CRAWLER.md).

---

## 1. `Listing` — `app/core/models/listing.py`

One property, as the engine sees it. Every financial figure is an integer in
**تومان** (never ریال), and every coordinate is inside the Tehran bounding box
(`35.55–35.85 N`, `51.10–51.60 E`) — the model enforces both.

### Identity and place

| Field | Notes |
| :-- | :-- |
| `id` | `divar-<token>` for crawled rows, `teh-<n>` for synthetic ones |
| `title`, `description` | Persian, as written by the advertiser |
| `neighborhood`, `neighborhood_key` | The key is the join to `matched_neighborhoods.geojson`; the search area filter runs on keys, never names |
| `district` | Official municipal district, e.g. `منطقه ۶` |
| `lat`, `lon`, `h3_index` | H3 resolution 8 |
| `location_precision`, `location_radius_meters` | `EXACT` / `FUZZY` / `NEIGHBORHOOD` — Divar blurs some points, and the pin is somewhere inside that radius |

### Money

| Field | Notes |
| :-- | :-- |
| `deposit_toman`, `rent_toman` | As advertised |
| `effective_monthly_cost` | `rent + deposit × 0.03`, precomputed and indexed |
| `can_convert` | قابلیت تبدیل |
| `convertible_deposit_max_toman` | The ceiling the advertiser accepts if rent is converted into deposit. Divar exposes this on its slider; absent means the band is inferred |
| `is_full_rahn` | رهن کامل — a flag, not a `rent == 0` test, because these are advertised with a token monthly rent rather than a literal zero |

### The property

`area_sqm`, `rooms`, `floor` (**−2 to 40** — basements are real stock in
Tehran and Divar lists them as منفی ۱/۲, so they are priced with a daylight
penalty rather than pretended away), `total_floors`, `has_elevator`,
`has_parking`, `has_balcony`, `has_storage`, `building_age_years`,
`build_year` (شمسی), `units_per_floor`, `min_contract_months`, `direction`,
`kitchen_type`, `is_renovated`, `is_furnished`, `has_pool`, `has_sauna`,
`has_jacuzzi`, `pets_policy`, `features` (Divar's `other_features` grouped by
facet), `suitable_for`, `attributes` (the مشخصات table verbatim).

### Transit

`nearest_metro_id`, `nearest_metro_name`, `dist_to_metro_meters`,
`metro_walk_mins` (= metres ÷ 80), `in_tarh_terafik`, `in_tarh_aloodegi`.

### Classification

| Field | Notes |
| :-- | :-- |
| `is_shared_living` | **Not a whole home.** A room, bed or flatmate advert, or a parking space let on its own. Divar files all of these under the same `apartment-rent` category as apartments, and they quote a fraction of a whole-unit price — so mixed in they would dominate the cheap tail of every search and make ordinary rentals look overpriced. The app offers them as their own market (هم‌خانه و خوابگاه). Classified by `app/core/shared_living.py` |

### Provenance and media

| Field | Notes |
| :-- | :-- |
| `provenance` | **Per field, where its value came from**: `divar_structured`, `divar_attribute`, `listing_text`, `estimated_from_area`… The detail page marks text-derived values, so a user can tell an advertiser's typed fact from something read out of their prose |
| `source`, `source_url` | |
| `images`, `image_count`, `images_are_authentic` | The last is the advertiser's own answer to «تصویرها برای همین ملک است؟» |
| `embedding` | 1536-dim description vector, optional |
| `created_at` | |

---

## 2. `ExtractedSearchIntent` — `app/core/models/search_intent.py`

What a search *is*, whether it came from the panel or from a Persian sentence.
Both paths produce this same object, which is why the two modes rank
identically.

* **Money** — `min/max_deposit`, `min/max_rent`, `can_convert`,
  `convertible_only`, `full_rahn_only`, `financial_persona`
  (`prefer_higher_rent` protects liquidity, `prefer_higher_deposit` protects
  monthly cash flow, `balanced` leaves the advertised split alone).
* **Property** — `min/max_area_sqm`, `min_rooms`, `min/max_floor`,
  `min_build_year`, `must_have_elevator|parking|storage|balcony|images`.
* **Market** — `living_kind`: `standard` (whole homes) or `shared`. Never
  both.
* **Place** — `target_neighborhoods` (Persian names as stated) and
  `target_neighborhood_keys` (resolved against the polygons). The filter runs
  on the keys; the names are kept so the UI can show what was understood.
* **Commute** — `workplace_lat/lon/name`, `max_commute_mins`, `commute_mode`
  (`walk|transit|drive`), `commute_importance` (0..1 — at 0 the criterion is
  dropped and its weight redistributed).
* **Soft** — `soft_preferences` (`["نورگیر عالی", "کوچه خلوت"]`) and
  `soft_preference_summary`, which is what gets embedded.
* **Weights** — `CriteriaWeights`, nine relative floats normalised to sum to
  1. Only the conversational path sets these: "مهم‌ترین چیز برام نزدیکی به
  مترو است، قیمت مهم نیست" is a statement about weights, not filters. The
  panel expresses the same thing in three steps per criterion.

Serialised with `exclude_unset`, so an absent field means **"the user did not
mention this"**, never "clear it". The whole chat→filter sync depends on that
distinction.

---

## 3. SQLite — `app/data/database.py`

One file. Two jobs, deliberately split.

```sql
CREATE TABLE listings (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    -- Typed, indexed columns: everything the search narrows on, so the
    -- database never deserialises anything to answer a filter.
    neighborhood_key, district,
    deposit_toman, rent_toman, effective_monthly_cost,
    can_convert, is_full_rahn, is_shared_living,
    area_sqm, rooms, floor, total_floors,
    has_elevator, has_parking, has_balcony, has_storage, build_year,
    lat, lon, h3_index, metro_walk_mins,
    in_tarh_terafik, in_tarh_aloodegi,
    image_count, is_furnished, is_renovated, pets_policy, source,
    -- Identity of the *property*, as opposed to the advert.
    fingerprint TEXT NOT NULL,
    -- Pre-normalised for FTS; display strings live in the payload.
    search_text TEXT NOT NULL,
    -- The whole Listing, as JSON.
    payload TEXT NOT NULL
);

CREATE VIRTUAL TABLE listings_geo USING rtree(id, min_lat, max_lat, min_lon, max_lon);
CREATE VIRTUAL TABLE listings_fts USING fts5(
    search_text, content='listings', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE embeddings (rowid INTEGER PRIMARY KEY REFERENCES listings(rowid) ON DELETE CASCADE,
                         dimension INTEGER NOT NULL, vector BLOB NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

**Columns *and* a document.** The duplication is deliberate: the columns exist
so the database can narrow candidates without parsing JSON, and the document
exists so hydration is one `json.loads` and a new optional field on the model
needs no migration.

**Indexes are ordered by what the UI narrows on first** — an area or
neighborhood bound, then price — so the common search is a range scan on one
index rather than a table scan. `is_shared_living` leads its composite because
every search filters on it first.

**`fingerprint`** hashes the fields that identify a *property* rather than an
*advert*. Divar reposts the same flat under a fresh token when an ad expires;
without this the same home appears three times in one result page. `upsert`
keeps exactly one row per property while still updating a row whose own token
comes round again — its price or photos may have moved.

**Connections** open in WAL mode with a 64 MB page cache and memory-mapped
reads. The corpus is read-almost-only, and WAL means a rebuild in one process
does not block queries in another.

### Migrations

`migrate()` runs on write and is idempotent. It exists because a corpus takes
hours to build and a new classifier has to reach the rows already stored.

The parking-classification stamp in `meta` records a **revision**, not a
boolean: that rule is read off advertisers' spelling and keeps meeting new
ways to write "parking" (پارکینگ, پارکینک, پارگینگ, پارگینک so far), so
bumping `_PARKING_RULE_REVISION` makes every existing database re-run it on
its next write.

---

## 4. Synthetic data

`app/data/synthetic_generator.py` is the fallback when no database exists at
all: 3,000 listings spread round-robin across the real neighborhood polygons —
roughly a dozen per محله, so narrowing to one محله plus a budget and an area
range still returns a usable set rather than nothing.

It is a *fallback*, not a fixture. If you see `[maskan] no database found` in
the log, the shipped seed did not unpack, and `GET /api/v1/health` will report
~3,000 rows instead of 21,377.
