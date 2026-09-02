# Frontend: State, Sync and the Map

Next.js 14 App Router, React 18, TypeScript, Tailwind, Zustand. One page, three
columns, one store.

```
┌───────────────────────────────────────────────────────────────────────┐
│ Header — mode switch · city picker                                    │
├──────────────────┬───────────────────┬────────────────────────────────┤
│ FilterPanel      │ ListingFeed       │ NeshanMap                      │
│   or ChatPanel   │ ranked cards      │ pins · clusters · outlines     │
│ (hidden in       │ ٪ badge, paging   │ search area · stations         │
│  map-explore)    │                   │                                │
└──────────────────┴───────────────────┴────────────────────────────────┘
        on a phone: three tabs, one visible at a time
```

`<html lang="fa" dir="rtl">`. Every layout property is logical (`ps-`, `pe-`,
`border-s`), never left/right.

---

## 1. The store — `store/useSearchStore.ts`

One Zustand store holds the filters, the results, the map viewport, the chat
transcript and the mode. Both input panels write into it and both output
surfaces read from it, which is the only reason the chat and the filters can
stay in agreement.

```ts
interface FilterState {
  // Mode, and what this deployment can offer
  mode: "ranked" | "chat" | "map";
  aiSearchEnabled: boolean;      // false → the chat mode is shown disabled
  exploreMapEnabled: boolean;    // false → the map mode is hidden entirely

  // Filters
  queryText: string;
  minDepositToman; depositToman; minRentToman; rentToman;
  minAreaSqm; maxAreaSqm; rooms; minFloor; maxFloor; minBuildYear;
  hasElevator; hasParking; hasBalcony; hasStorage; hasImages;
  fullRahnOnly; convertibleOnly;
  livingKind: "standard" | "shared";
  financialPersona: FinancialPersona;
  selectedNeighborhoods: string[];   // keys, not titles
  searchInViewport: boolean;         // the box replaces the selection

  // How much each criterion counts — reorders, never filters
  criteriaWeights: Record<WeightedCriterion, "low" | "normal" | "high">;

  // Workplace / commute
  workplaceLocation: { lat; lon; name } | null;
  maxCommuteMins: number;
  commuteImportance: number;         // 0..1; 0 drops the criterion
  commuteMode: "walk" | "transit" | "drive";

  // Map & viewport
  mapBBox; mapZoom;
  restoreBounds: BBoxFilter | null;    // where the map was before it flew
  searchAreaBounds: BBoxFilter | null; // the search area's own rectangle
  selectedListingId; hoveredListingId;

  // Results — one ranked list
  results: ListingResult[];
  mapPoints: MapPoint[];
  mapClusters: MapCluster[];
  focusedListing: ListingResult | null;
  totalCount; page; isLoading; isLoadingMore; searchError;

  // Chat
  chatMessages; isChatStreaming; chatError;
}
```

### One list, not two

`results` replaced `tier1Results` / `tier2Results`. The feed renders it in
order and each card prints its own ٪ badge; the tier headings that used to
divide them restated that number as a wall the user had to click through. See
[ALGORITHMS.md §6](ALGORITHMS.md).

### The three fields that keep the user's place

`selectedListingId`, `restoreBounds` and `searchAreaBounds` exist so that
looking at one property never costs you the search you were reading.

`restoreBounds` is the viewport as it stood *before* the map flew to a
listing, so deselecting returns the map to exactly that rectangle rather than
approximately. `searchAreaBounds` is the rectangle the **search area itself**
occupies — the selected neighborhoods' dissolved outline — because with
neighborhoods chosen the map is free to be panned anywhere without changing
what is searched, and "back to the search area" then has to mean the area, not
the last place the map happened to be looking.

### `setMode` — what is and is not cleared

```ts
setMode(mode) {
  if (mode === previous) return;
  if (mode === "chat" && !aiSearchEnabled) return;
  if (mode === "map"  && !exploreMapEnabled) return;

  // ranked ↔ chat: only the input panel changes. Nothing is cleared,
  // nothing is re-fetched.
  if (previous !== "map" && mode !== "map") { set({ mode }); return; }

  set({ mode, ...MODE_SCOPED_RESET, isLoading: true });
  if (mode !== "map") void runSearch();     // map's first search comes from the map
}
```

The two ranked modes are **the same ranked search over the same filters**, one
with a sentence of Persian added, so the results on screen are still the right
answer after the switch. Clearing them threw the list away, sent the feed back
to the top, dropped the selected listing and flew the map home — a change of
input panel that cost the user their place.

Map-explore *is* a different search — unranked, viewport-driven, no scores, no
paging — so entering or leaving it clears results, viewport state and
selection. Its first search is issued by the map, which is the only thing that
knows the viewport being searched.

Two related invariants that are easy to break by accident:

* **A mount is not a filter change.** The filter panel's debounced search
  effect skips its first run, because the panel is unmounted while the user is
  in the chat and mounted again when they come back — searching on arrival
  discarded the list they were reading to fetch the same results a second
  time.
* **Only a change of *selection* flies the map.** The fly-to effect depends on
  the selected id and the points, and deliberately not on the mode or the
  viewport flags it reads at selection time; adding them made a panel swap
  yank the map off wherever the user had since dragged it.

---

## 2. Chat ⇄ filters

```
 «ودیعه تا ۳۰۰ میلیون با آسانسور، نزدیک مترو شادمان»
                     │
                     ▼  POST /chat/stream  (SSE)
        token · token · token …            → rendered live
        state_update { extracted_intent }
                     │
                     ▼  syncFromExtractedIntent()
        ┌──────────────────────────────────┐
        │ depositToman   = 3_000_000_000   │
        │ hasElevator    = true            │
        │ selectedNeighborhoods = ["146"]  │
        └──────────────┬───────────────────┘
                       ▼
        The panel now shows those values — visible, and correctable.
                       │
                       ▼  runSearch()
        The same POST /search the panel would have sent.
```

Three rules make this safe:

* **Only fields the model actually set are applied.** The backend serialises
  with `exclude_unset`, so `undefined` means "the user did not mention this",
  never "clear it".
* **Keys only.** A place name the backend could not resolve to a polygon is
  not a selectable search area, and putting it in the filters would render as
  a chip the user cannot act on.
* **Nothing is applied invisibly.** Whatever the model understood appears in
  the panel, one click away, where it can be corrected. That is what makes a
  بتا feature honest.

The conversational mode's own search still travels as `mode: "ranked"`: free
text alone cannot rank without a chat turn, so what actually goes to `/search`
is the filters the conversation produced.

---

## 3. The map — `components/Map/`

A Leaflet container with a **MapLibre GL vector basemap** underneath it
(`@maplibre/maplibre-gl-leaflet`). No Neshan SDK, no API key, no tile bill.

### The basemap

Divar's map is not a public product and no open-source style matches it off
the shelf. It is, however, plain OpenStreetMap data rendered through a
deliberately quiet custom style: near-white land, sage parks, white local
streets, one strong accent for highways, small grey Persian labels, and
nothing else competing for attention. That is reproducible on open vector
tiles, and `lib/divarMapStyle.ts` is that reproduction, over
[OpenFreeMap](https://openfreemap.org)'s free no-key planet.

Vector rather than raster is what makes it possible at all: colours, road
widths, which features exist at which zoom, and label language are decided on
the client. Labels prefer OSM's `name:fa` and fall back to the local name.

Two files are self-hosted, vendored out of `node_modules` at `pre(dev|build)`
by `scripts/copy-map-assets.mjs`:

* **the MapLibre worker** — MapLibre finds it relative to `import.meta.url`,
  which webpack rewrites; the worker then loads nothing, raises nothing, and
  every tile sits in "loading" forever against a blank map;
* **`mapbox-gl-rtl-text`** — loaded into that worker by URL, required for
  Persian labels to be shaped and ordered correctly.

### Layers

| Layer | Behaviour |
| :-- | :-- |
| Listing pins | Coloured on one shared match scale (`lib/matchColor.ts`) — the listing's own utility, not stretched across the loaded page, so a pin means the same thing everywhere |
| Cluster badges | Server-built (`app/search/map_clusters.py`). Pins + badges account for every match, so the badge counts add up to the number above the feed. Clicking one flies into its rectangle |
| محله outlines and labels | Drawn for the current selection; labels appear when there is room for them |
| Search-area outline | The selection dissolved server-side into one shape — the borders between two chosen محله are an artefact of how the city is subdivided, not a boundary of the search |
| Congestion zones | Outlines with a small pill label, never a filled wash |
| Metro / BRT stations | Only past zoom 14, where they are useful |
| Commute isochrone | One merged outline, not ~130 stacked circles |
| Workplace pin | Placed by map click or by Nominatim address search |

### Interaction rules

* **The map navigates on click, never on hover.** Hovering a card highlights
  its pin (and vice versa) — it does not move the map. Flying somewhere the
  user did not ask to go, while they are reading, is the fastest way to make a
  map feel hostile.
* **Selecting anywhere selects everywhere.** A card or a pin sets
  `selectedListingId`; the feed scrolls that card into view and the map flies
  to that pin. One gesture, not two the user has to connect.
* **A pin with no card is fetched on its own.** Map-explore plots the whole
  viewport but pages the feed 30 at a time, so most pins have no card loaded.
  The clicked one is fetched and appended as `focusedListing`, where it
  behaves exactly like any other card.
* **Deselecting returns the map**, to `searchAreaBounds` when there is a drawn
  area and to `restoreBounds` otherwise.

---

## 4. Feed and cards

* One ranked list, `${count} ملک · مرتب‌شده بر اساس میزان تطابق` above it.
* First page 60, then 30 at a time via «نمایش موارد بیشتر» — and paging
  continues from **how many results are held**, not from page arithmetic,
  because the first page is bigger than the rest.
* Card-shaped skeletons during the first load; a spinner on an empty panel
  reads as "nothing here", these read as "results are coming".
* Prices in Persian digits with thousands separators; «با تبدیل» whenever the
  shown split is not the advertised one.
* The trade-off sentence, when a result earned one.
* In map-explore the ٪ badge is hidden — nothing was ranked, so there is no
  match to assert.

---

## 5. Design rules that are easy to undo

* **No visible scrollbars anywhere** (`globals.css`). Wheel, touch, keyboard
  and drag-to-scroll all behave exactly as before; only the gutter is gone.
* **Persian type is set one notch larger than Tailwind's defaults**, with
  opened line heights. Persian sits lower and denser than Latin at the same
  nominal size and this UI is read at a glance while scanning a feed. 13.5px
  is the smallest legitimate type in the product.
* **The font stack carries emoji faces on purpose.** Persian adverts use ✅ and
  ☎ as bullet characters and Vazirmatn has none of them — without the fallback
  every one renders as a tofu box mid-sentence.
* **`dvh` where it exists.** On a phone `100vh` is the height the window would
  have with the browser's bars retracted, so a `100vh` layout is always taller
  than the screen actually showing it.
* **Every user-facing string is Persian**, including error messages, which
  come from the backend already written for the user rather than being
  translated in the client.
