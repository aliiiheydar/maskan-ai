"use client";

// Neshan's Web SDK requires a paid API key that isn't configured in this repo
// (see .env.example -- only OpenRouter keys are provisioned). Leaflet is used
// instead, per the CLAUDE.md-approved "Leaflet / MapLibre / Neshan Web SDK"
// options, with a self-styled OpenFreeMap vector basemap (see
// VectorBaseLayer / divarMapStyle). Everything else here -- markers, bbox
// sync, congestion zones -- is basemap-agnostic.
import "leaflet/dist/leaflet.css";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import L from "leaflet";
import { MapContainer, Marker, Polygon, Popup, useMap, useMapEvents } from "react-leaflet";

import { getCongestionZones, getTransitStations } from "@/lib/api";
import { useSearchStore } from "@/store/useSearchStore";
import { matchColor } from "@/lib/matchColor";
import type { CongestionZone, GeoJSONGeometry, MapCluster, MapPoint, ListingResult, TransitStation } from "@/types";
import { toLeafletRings } from "./lib/geometry";
import { useIsDesktop } from "@/lib/breakpoints";
import { isOnScreen, whenMapIsVisible } from "./lib/visibility";
import NeighborhoodLabels from "./NeighborhoodLabels";
import NeighborhoodMapPicker from "./NeighborhoodMapPicker";
import SearchAreaOverlay from "./SearchAreaOverlay";
import VectorBaseLayer from "./VectorBaseLayer";
import WorkplacePicker from "./WorkplacePicker";

const CONGESTION_ZONE_COLORS: Record<CongestionZone["zone"], string> = {
  tarh_terafik: "#ec4899",
  tarh_aloodegi: "#3b82f6",
};

// Centred on the city polygon rather than on the historic centre, at the zoom
// where all of Tehran fits the map pane -- the default search area is the
// whole city, so the default view should show the whole of it.
const TEHRAN_CENTER: [number, number] = [35.7, 51.36];
// Tehran's bounding box, verbatim from CLAUDE.md's geospatial invariants.
const TEHRAN_MIN_LAT = 35.55;
const TEHRAN_MAX_LAT = 35.85;
const TEHRAN_MIN_LON = 51.1;
const TEHRAN_MAX_LON = 51.6;
const DEFAULT_ZOOM = 11;
// Leaflet normally infers the map's zoom range from its raster TileLayer.
// The basemap is a GL layer, which declares no zoom range, so it has to be
// stated here. 19 is past the vector tiles' own maxzoom (14), which is fine --
// MapLibre overzooms them rather than dropping out.
const MAX_ZOOM = 19;

/** The city, and a margin around it.
 *
 * Everything this app knows -- listings, neighborhood polygons, the transit
 * graph, the congestion zones -- is Tehran's (see CLAUDE.md's bounding box),
 * so panning to Karaj or Qom can only ever show an empty map. The viewport is
 * therefore clamped to the city plus a padding ring: wide enough that the
 * northern and southern edges of Tehran are comfortably reachable and the
 * surroundings stay visible for context, tight enough that the user can never
 * lose the city off-screen. `maxBoundsViscosity: 1` makes the edge solid
 * rather than elastic, so a drag stops at the boundary instead of springing
 * back from beyond it.
 */
const TEHRAN_PAD_LAT = 0.09;
const TEHRAN_PAD_LON = 0.13;
const TEHRAN_MAX_BOUNDS: [[number, number], [number, number]] = [
  [TEHRAN_MIN_LAT - TEHRAN_PAD_LAT, TEHRAN_MIN_LON - TEHRAN_PAD_LON],
  [TEHRAN_MAX_LAT + TEHRAN_PAD_LAT, TEHRAN_MAX_LON + TEHRAN_PAD_LON],
];
// Zooming out past the padded box would put the clamp in a fight with the
// viewport (Leaflet cannot honour bounds smaller than the visible world), so
// the range stops where the padded city fills a typical pane -- which is the
// same zoom the map opens at.
const MIN_ZOOM = DEFAULT_ZOOM;

/**
 * Continuous, un-snapped zoom.
 *
 * Leaflet's default is one whole zoom level per wheel notch, snapped to
 * integers: the map jumps in steps, and on a trackpad -- where a single
 * gesture is dozens of small deltas -- it lurches. `zoomSnap: 0` lets the map
 * settle at fractional zooms, and a smaller `wheelPxPerZoomLevel` makes each
 * notch travel less, so a scroll moves the scale by about as much as the
 * gesture asked for. The vector basemap renders at any scale, so there is no
 * tile grid to snap back to.
 *
 * This is Leaflet's own wheel handler throughout -- it batches the gesture and
 * runs one animated zoom, which transforms the map pane rather than
 * re-projecting every marker. Driving the zoom per frame ourselves was tried
 * instead and reverted: re-projecting on every frame rounds each marker and
 * polygon vertex to a whole pixel, which is what made them shiver.
 */
const ZOOM_SNAP = 0;
// One whole level per button press. The buttons are the coarse control -- the
// wheel is the fine one -- and a fractional step made them feel unresponsive.
const ZOOM_DELTA = 1;
// The wheel distance that adds up to one whole zoom level. Higher is slower
// and finer; this is roughly a third of Leaflet's default, which is what turns
// a notch-per-level jump into a glide.
const WHEEL_PX_PER_ZOOM_LEVEL = 180;
// How long the wheel deltas are gathered before one zoom is run. Short enough
// to feel immediate, long enough that a trackpad flick is a single motion.
const WHEEL_DEBOUNCE_MS = 12;

/** How long the map has to sit still before a viewport search is issued.
 *
 * The search is deliberately tied to the map *stopping*, not to it moving:
 * a drag across the city or a zoom out through five levels would otherwise
 * fire a query for every intermediate rectangle the user was never looking
 * at. Any new movement cancels the pending search outright. */
const VIEWPORT_SETTLE_MS = 350;
// Below this zoom, individual stations would just clutter a city-wide view
// (matches Divar's progressive-disclosure behavior for its own station layer).
const TRANSIT_STATION_MIN_ZOOM = 14;
// Half a zoom level either side of the threshold the markers are mounted but
// transparent, which is what gives the layer something to animate between
// instead of blinking in and out.
const TRANSIT_STATION_FADE_BAND = 0.75;
/** Zoom the map flies to when the user opens one property. */
const FOCUS_ZOOM = 16;

/**
 * Until this timestamp, a moveend was caused by us, not by the user.
 *
 * Focusing a listing moves the viewport, and in viewport-search mode a moved
 * viewport is a new search. Without this guard, looking at one property would
 * silently replace the search that found it.
 */
let programmaticMoveUntil = 0;

function beginProgrammaticMove(durationSeconds: number) {
  // The animation itself, plus the settle window, plus slack for the moveend
  // that lands at the end of it.
  programmaticMoveUntil = Date.now() + durationSeconds * 1000 + VIEWPORT_SETTLE_MS + 250;
}

function workplaceIcon() {
  // A drawn glyph rather than the 💼 emoji it used to be: an emoji renders in
  // whatever the operating system decided it looks like -- glossy on one
  // machine, flat on another, a different colour on a third -- which is not
  // something a map's own iconography can be left to.
  //
  // Shape and colour both have to say "this is not a listing". Listing pins
  // are circles coloured on a red -> amber -> green match ramp (matchColor),
  // so the amber circle this used to be was indistinguishable at a glance
  // from a mediocre match sitting next to it. A violet rounded square instead:
  // the hue is nowhere on the match ramp, and the silhouette reads as
  // different even in the corner of the eye.
  return L.divIcon({
    className: "",
    html: `<span style="
      display:flex;align-items:center;justify-content:center;
      width:30px;height:30px;border-radius:9px;
      background:#6d28d9;border:2.5px solid white;
      box-shadow:0 0 0 1px rgba(15,23,42,.18), 0 3px 8px rgba(0,0,0,.35);
    "><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="white"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2.5" y="7.5" width="19" height="12.5" rx="2.5"/>
        <path d="M9 7.5V5.5a1.8 1.8 0 0 1 1.8-1.8h2.4A1.8 1.8 0 0 1 15 5.5v2"/>
        <path d="M2.5 12.8h19"/>
      </svg></span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function pinIcon(options: { color: string; opacity: number; isFocused: boolean }) {
  const { color, opacity, isFocused } = options;
  const size = isFocused ? 30 : 22;
  // The focused pin has to be findable in a field of dozens of others, so it
  // is marked three ways at once: it grows, it pulses, and it gains a dark
  // ring outside its white edge. The ring is what actually does the work --
  // size alone is ambiguous where pins overlap, and the pulse only reads once
  // the eye is already on it. It is drawn with box-shadow rather than a
  // border so the pin's own geometry does not shift as it lights up.
  const ring = isFocused ? "box-shadow:0 0 0 3px rgba(15,23,42,.9), 0 2px 8px rgba(0,0,0,.45);" : "box-shadow:0 1px 4px rgba(0,0,0,.4);";
  return L.divIcon({
    className: "",
    html: `<span style="
      display:block;width:${size}px;height:${size}px;border-radius:9999px;
      background:${color};opacity:${isFocused ? 1 : opacity};
      border:2px solid white;${ring}
      transition:width .2s,height .2s,box-shadow .2s;
      ${isFocused ? "animation:maskan-pulse 1s ease-in-out infinite;" : ""}
    "></span>
    <style>
      @keyframes maskan-pulse { 0%,100%{opacity:1;} 50%{opacity:.55;} }
    </style>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}


/** Pins overlap constantly at city zoom, so the focused one is lifted above
 * the rest of the layer -- otherwise the pin the user is pointing at can be
 * half-hidden behind a neighbour that merely happens to be drawn later. */
const FOCUSED_PIN_Z = 1000;


/** The "open this one" affordance that appears on a selected pin. Selecting
 * and opening are separate gestures on purpose: a click on the map says
 * "which one is this?", and only this button says "show me the details". */
function actionIcon() {
  return L.divIcon({
    className: "listing-action",
    html: `<span>مشاهده ملک</span>`,
    iconSize: undefined,
  });
}

/** Divar's own station mark: a yellow rounded tile carrying a metro-car
 * pictogram, with the station name beneath it (divar-map-screenshots/5.png,
 * whose tile samples as #f7d752 with a #404041 glyph). BRT stops are
 * deliberately absent -- with ~360 nodes in the city they crowd out the
 * listings, and it is the metro people choose a neighborhood by.
 *
 * `visible` drives the fade rather than mounting/unmounting the marker: a
 * layer that simply appears at a zoom threshold pops, and Divar's own station
 * layer eases in. The marker stays mounted through a band either side of the
 * threshold (see MetroStations) so both directions animate. */
function metroIcon(name: string, visible: boolean) {
  // Zero-sized and anchored at its own origin, so the point Leaflet positions
  // is the station's coordinate itself. The tile and the label are then placed
  // relative to that origin in CSS (.metro-station in globals.css). Sizing the
  // icon to the whole tile-plus-label block instead would centre the *block*
  // on the station, leaving the tile floating above it by half a label.
  return L.divIcon({
    className: `metro-station${visible ? " metro-station--visible" : ""}`,
    // A train seen head-on -- rounded car body, window band, two headlights,
    // and the rails under it. The previous glyph was an outlined wedge with a
    // single dot, which at 11px read as a generic marker rather than as
    // anything to do with the metro; a front-on car is the pictogram transit
    // maps the world over settled on precisely because it survives being
    // small.
    html: `<span class="metro-station__mark">
      <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
           fill="none" stroke="#404041" stroke-width="1.9"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="5.5" y="2.6" width="13" height="14.4" rx="4.2"/>
        <path d="M5.5 9.4h13"/>
        <circle cx="9.4" cy="13.2" r="1.15" fill="#404041" stroke="none"/>
        <circle cx="14.6" cy="13.2" r="1.15" fill="#404041" stroke="none"/>
        <path d="M9 17.2 7 21M15 17.2 17 21"/>
      </svg>
    </span><span class="metro-station__name">${name}</span>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

/** Divar's numbered map badge: how many properties are in this part of the
 * viewport, drawn where they actually are. Sized by magnitude so a cell of
 * 1,400 reads as bigger than one of 130 before the number is even read. */
function clusterBadge(count: number) {
  const size = count < 100 ? 34 : count < 1000 ? 42 : 50;
  return L.divIcon({
    className: "",
    html: `<div style="
      display:flex;align-items:center;justify-content:center;
      width:${size}px;height:${size}px;border-radius:9999px;
      background:#15803d;color:white;font-weight:700;font-size:${count < 1000 ? 12 : 11}px;
      border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.4);
    ">${count.toLocaleString("fa-IR")}</div>`,
    iconSize: L.point(size, size),
    iconAnchor: [size / 2, size / 2],
  });
}

/** One counted cell. Clicking it flies to the rectangle it covers, which is
 * the gesture that opens it: a smaller viewport means fewer matches per cell,
 * and the server sends the ones that got small enough as individual pins. */
function ClusterBadge({ cluster }: { cluster: MapCluster }) {
  const map = useMap();
  return (
    <Marker
      position={[cluster.lat, cluster.lon]}
      icon={clusterBadge(cluster.count)}
      eventHandlers={{
        click: () => {
          // Deliberately *not* wrapped in beginProgrammaticMove: flying into a
          // cell is the user asking to search there, so the moveend must run a
          // new search. That search is what opens the cell -- a smaller
          // viewport means fewer matches per cell, and the ones that fit come
          // back as individual pins.
          map.flyToBounds(
            L.latLngBounds(
              [cluster.min_lat, cluster.min_lon],
              [cluster.max_lat, cluster.max_lon],
            ),
            { duration: 0.6, padding: [20, 20] },
          );
        },
      }}
    />
  );
}

/** A ranked listing's pin: coloured by its match, selected on click. */
function ListingMarker({ listing }: { listing: ListingResult }) {
  const hoveredListingId = useSearchStore((state) => state.hoveredListingId);
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);
  const setHoveredListingId = useSearchStore((state) => state.setHoveredListingId);
  const { fill, opacity } = matchColor(listing.utility_score);

  const isFocused = listing.id === hoveredListingId || listing.id === selectedListingId;

  return (
    <Marker
      position={[listing.lat, listing.lon]}
      icon={pinIcon({ color: fill, opacity, isFocused })}
      zIndexOffset={isFocused ? FOCUSED_PIN_Z : 0}
      eventHandlers={{
        // Clicking the pin that is already selected releases it, exactly as
        // clicking its card again does -- the same gesture undoes itself on
        // either surface, and the map returns to the search area.
        click: () => setSelectedListingId(selectedListingId === listing.id ? null : listing.id),
        // Pointing at a pin highlights it and its card together, which is the
        // same coupling the feed already drives in the other direction.
        mouseover: () => setHoveredListingId(listing.id),
        mouseout: () => setHoveredListingId(null),
      }}
    />
  );
}

/** A map pin for a listing the feed hasn't loaded.
 *
 * In map-explore the feed is paginated but the pins are not (see MapPoint), so
 * most pins have no card behind them. Nothing is fetched on click -- selecting
 * a pin only says "this one"; the details arrive when the user presses the
 * button that appears on it. */
function MapPointMarker({ point }: { point: MapPoint }) {
  const hoveredListingId = useSearchStore((state) => state.hoveredListingId);
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);
  const setHoveredListingId = useSearchStore((state) => state.setHoveredListingId);

  const isFocused = point.id === hoveredListingId || point.id === selectedListingId;

  return (
    <Marker
      position={[point.lat, point.lon]}
      icon={pinIcon({ color: "#15803d", opacity: 1, isFocused })}
      zIndexOffset={isFocused ? FOCUSED_PIN_Z : 0}
      eventHandlers={{
        click: () => setSelectedListingId(selectedListingId === point.id ? null : point.id),
        mouseover: () => setHoveredListingId(point.id),
        mouseout: () => setHoveredListingId(null),
      }}
    />
  );
}

/** The button that sits on the selected pin and opens its detail view. */
function SelectedListingAction({
  positions,
  cardIds,
}: {
  positions: Map<string, [number, number]>;
  cardIds: Set<string>;
}) {
  const router = useRouter();
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const isDesktop = useIsDesktop();
  const target = selectedListingId ? positions.get(selectedListingId) : undefined;

  if (!selectedListingId || !target) return null;
  // A pin the feed has a card for is opened from that card: the button sits on
  // the property the user is reading, not floating over the map. Only
  // map-explore's unpaged pins -- which have no card behind them -- still need
  // the affordance out here.
  //
  // That reasoning holds only while the card is actually on screen. On a phone
  // the feed and the map are tabs, and selecting from the feed brings the map
  // forward, so the card carrying «مشاهده ملک» is precisely what the user can
  // no longer see -- and without this the selected property would have no way
  // to be opened at all.
  if (isDesktop && cardIds.has(selectedListingId)) return null;

  return (
    <Marker
      position={target}
      icon={actionIcon()}
      // Above every other pin: it is drawn on top of the one it belongs to.
      zIndexOffset={2000}
      eventHandlers={{
        click: () => router.push(`/listing/${encodeURIComponent(selectedListingId)}`, { scroll: false }),
      }}
    />
  );
}

/** Keeps the map's idea of its own size honest.
 *
 * Leaflet measures its container once, on mount, and never again -- so any
 * layout change around it (the filter column disappearing in map-explore, a
 * window resize, a devtools pane opening) leaves the map rendering into the
 * old rectangle, with a dead grey band where the new space is. A
 * ResizeObserver on the container is the general fix: whatever moves, the map
 * re-measures.
 */
function ResizeSync() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    const observer = new ResizeObserver(() => {
      // A tab switch on a phone takes the map to 0x0 (see app/page.tsx), and
      // re-measuring *that* teaches Leaflet a viewport of nothing -- which it
      // then reports as a moveend with a collapsed bounding box. Sizes of zero
      // are not sizes; the map keeps the last real one until it is back.
      if (container.clientWidth === 0 || container.clientHeight === 0) return;
      map.invalidateSize({ animate: false });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);

  return null;
}

/**
 * Reports the viewport back to the shared store as the search area, once the
 * map has stopped moving.
 *
 * Active in map-explore and in the filter panel's "جستجو در محدوده نقشه", and
 * suspended entirely while the user is looking at one property: flying to a
 * listing is navigation, not a new search, so the box that found it is kept
 * until they come back to it (see restoreBounds).
 */
function BBoxSync() {
  const mode = useSearchStore((state) => state.mode);
  const searchInViewport = useSearchStore((state) => state.searchInViewport);
  const restoreBounds = useSearchStore((state) => state.restoreBounds);
  const setFilters = useSearchStore((state) => state.setFilters);
  const runSearch = useSearchStore((state) => state.runSearch);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const isActive = mode === "map" || searchInViewport;

  const map = useMapEvents({
    // Any new motion cancels a search that was queued for the previous stop.
    movestart: () => clearTimeout(timerRef.current),
    zoomstart: () => clearTimeout(timerRef.current),
    moveend: () => {
      if (!isActive) return;
      // Off-screen: on a phone the map is a tab, and a hidden one has no
      // viewport to search. Left unguarded, moving to the feed collapsed the
      // map to 0x0, and the bounding box of nothing matched no listing -- the
      // list the user had just switched to emptied itself a beat later.
      if (!isOnScreen(map)) return;
      // Our own fly/pan, not the user's (see programmaticMoveUntil).
      if (Date.now() < programmaticMoveUntil) return;
      // Focused on one property: the search area is being held for them.
      if (restoreBounds) return;
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        const bounds = map.getBounds();
        setFilters({
          mapZoom: map.getZoom(),
          mapBBox: {
            minLat: bounds.getSouth(),
            minLon: bounds.getWest(),
            maxLat: bounds.getNorth(),
            maxLon: bounds.getEast(),
          },
        });
        runSearch();
      }, VIEWPORT_SETTLE_MS);
    },
  });

  // Turning viewport search on is itself a viewport search: without this the
  // first results would be the previous area until the user happened to pan,
  // so the count in the feed would disagree with the pins on screen. The
  // panel and setMode both leave this search to here, so there is no
  // duplicate request.
  useEffect(() => {
    if (!isActive) return;
    if (!isOnScreen(map)) return;
    const bounds = map.getBounds();
    setFilters({
      mapBBox: {
        minLat: bounds.getSouth(),
        minLon: bounds.getWest(),
        maxLat: bounds.getNorth(),
        maxLon: bounds.getEast(),
      },
    });
    void runSearch();
  }, [isActive, map, setFilters, runSearch]);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  return null;
}

/** The point on a zone's outline where its badge sits: the northernmost
 * vertex of the widest ring. Because it is a coordinate on the boundary
 * itself, the badge stays pinned to the same place on the line at every zoom
 * -- which is how Divar's "طرح ترافیک" pill behaves across its own zoom
 * levels (divar-map-screenshots/1-3.png). Anchoring to the polygon's centre
 * instead would float the label in empty space away from the line it names. */
function badgeAnchor(geometry: GeoJSONGeometry): [number, number] | null {
  const rings: number[][][] =
    geometry.type === "Polygon"
      ? (geometry.coordinates as number[][][])
      : (geometry.coordinates as number[][][][]).flat();

  let best: number[] | null = null;
  for (const ring of rings) {
    for (const point of ring) {
      if (best === null || point[1] > best[1]) best = point;
    }
  }
  return best ? [best[1], best[0]] : null;
}

function zoneBadgeIcon(label: string, color: string) {
  return L.divIcon({
    className: "zone-badge",
    html: `<span style="color:${color}">${label}</span>`,
    iconSize: undefined,
  });
}

/** Tarh-e Terafik / Tarh-e Aloodegi boundaries, drawn as one continuous
 * colored line with a small pill badge sitting on it -- same visual language
 * as Divar's map instead of a filled hazard-style overlay. Fetched once;
 * this data doesn't change at runtime. */
function CongestionZones() {
  const [zones, setZones] = useState<CongestionZone[]>([]);

  useEffect(() => {
    let cancelled = false;
    getCongestionZones()
      .then((response) => {
        if (!cancelled) setZones(response);
      })
      .catch(() => {
        if (!cancelled) setZones([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      {zones.map((zone) => {
        const color = CONGESTION_ZONE_COLORS[zone.zone];
        const anchor = badgeAnchor(zone.geometry);
        return (
          <Fragment key={zone.zone}>
            <Polygon
              positions={toLeafletRings(zone.geometry)}
              // Solid and heavier than a hairline: the zone boundary is a
              // real, continuous line on Divar's map, not a dashed hint.
              pathOptions={{ color, weight: 2.5, opacity: 0.95, fillOpacity: 0, lineJoin: "round", interactive: false }}
            />
            {anchor && (
              <Marker position={anchor} icon={zoneBadgeIcon(zone.label, color)} interactive={false} />
            )}
          </Fragment>
        );
      })}
    </>
  );
}

/** Metro station markers, only rendered once zoomed in past
 * TRANSIT_STATION_MIN_ZOOM -- at a city-wide zoom they would just be noise
 * (matches Divar's own progressive-disclosure behavior for its station
 * layer). Station list comes from the existing GET /transit/stations,
 * fetched once, with BRT stops filtered out. */
type StationBand = "hidden" | "fading" | "visible";

function stationBand(zoom: number): StationBand {
  if (zoom < TRANSIT_STATION_MIN_ZOOM - TRANSIT_STATION_FADE_BAND) return "hidden";
  return zoom >= TRANSIT_STATION_MIN_ZOOM ? "visible" : "fading";
}

function MetroStations() {
  const map = useMap();
  const [stations, setStations] = useState<TransitStation[]>([]);
  // Not the zoom itself: with a continuous glide the zoom changes every
  // frame, and re-rendering 150 markers per frame is what a smooth gesture
  // cannot afford. Only the band this layer actually reacts to is stored, so
  // the layer re-renders twice per gesture at most.
  const [band, setBand] = useState(() => stationBand(map.getZoom()));

  useMapEvents({
    zoom: (event) => {
      const next = stationBand(event.target.getZoom());
      setBand((current) => (current === next ? current : next));
    },
  });

  useEffect(() => {
    let cancelled = false;
    getTransitStations()
      .then((response) => {
        if (!cancelled) setStations(response.filter((station) => station.type === "metro"));
      })
      .catch(() => {
        if (!cancelled) setStations([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (band === "hidden") return null;
  const visible = band === "visible";

  return (
    <>
      {stations.map((station) => (
        <Marker key={station.id} position={[station.lat, station.lon]} icon={metroIcon(station.name, visible)}>
          <Popup>
            <div className="text-right text-xs">
              <p className="font-semibold">{station.name}</p>
              <p className="text-slate-500">ایستگاه مترو</p>
            </div>
          </Popup>
        </Marker>
      ))}
    </>
  );
}

/**
 * Brings the selected listing into view.
 *
 * Only a click moves the map. Hovering a card used to fly the map to it,
 * which meant the view drifted as the cursor ran down the feed and the user
 * had no way to read a list without the map chasing them; a hover now only
 * lights up the matching pin. When the map is the search area, the viewport
 * it is leaving is recorded first, so going to look at one property is
 * reversible rather than a silent re-search (see RestoreSearchAreaButton).
 */
function FocusedListingFly({ points }: { points: Map<string, [number, number]> }) {
  const map = useMap();
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const mode = useSearchStore((state) => state.mode);
  const searchInViewport = useSearchStore((state) => state.searchInViewport);
  const selectedNeighborhoods = useSearchStore((state) => state.selectedNeighborhoods);
  const restoreBounds = useSearchStore((state) => state.restoreBounds);
  const searchAreaBounds = useSearchStore((state) => state.searchAreaBounds);
  const setFilters = useSearchStore((state) => state.setFilters);

  useEffect(() => {
    if (!selectedListingId) {
      // Deselecting is the way back: the same click that focused a property
      // returns the map to the rectangle the search was run against, so going
      // to look at one is reversible with the gesture that started it.
      if (!restoreBounds) return;
      return whenMapIsVisible(map, () => {
        beginProgrammaticMove(0.7);
        map.flyToBounds(
          L.latLngBounds(
            [restoreBounds.min_lat, restoreBounds.min_lon],
            [restoreBounds.max_lat, restoreBounds.max_lon],
          ),
          { duration: 0.7 },
        );
        setFilters({ restoreBounds: null });
      });
    }
    const target = points.get(selectedListingId);
    if (!target) return;

    return whenMapIsVisible(map, () => {
      if ((mode === "map" || searchInViewport || selectedNeighborhoods.length > 0) && !restoreBounds) {
        // What "back" means depends on what defines the search area. When the
        // area is the viewport (map-explore, جستجو در محدوده نقشه) the
        // rectangle on screen *is* the search, so that is what gets kept. When
        // it is a set of neighborhoods, the search is the outline -- the map
        // may have been dragged far away from it without changing a single
        // result -- so coming back has to mean coming back to the outline, not
        // to the last place the map was pointed at.
        const area = mode !== "map" && !searchInViewport ? searchAreaBounds : null;
        const bounds = map.getBounds();
        setFilters({
          restoreBounds: area ?? {
            min_lat: bounds.getSouth(),
            min_lon: bounds.getWest(),
            max_lat: bounds.getNorth(),
            max_lon: bounds.getEast(),
          },
        });
      }

      beginProgrammaticMove(0.6);
      map.flyTo(target, Math.max(map.getZoom(), FOCUS_ZOOM), { duration: 0.6 });
    });
    // Only a change of selection flies the map. Everything else this reads --
    // restoreBounds, searchAreaBounds, and the mode/viewport/neighborhood
    // trio that decides what "back" means -- is read at the moment of
    // selection and deliberately not depended on: re-running on any of them
    // would fly to the same listing a second time, which is how swapping the
    // filter panel for the chat used to yank the map back off wherever the
    // user had since dragged it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedListingId, points, map, setFilters]);

  return null;
}

export default function NeshanMap() {
  const mode = useSearchStore((state) => state.mode);
  const tier1Results = useSearchStore((state) => state.tier1Results);
  const tier2Results = useSearchStore((state) => state.tier2Results);
  const mapPoints = useSearchStore((state) => state.mapPoints);
  const mapClusters = useSearchStore((state) => state.mapClusters);
  const focusedListing = useSearchStore((state) => state.focusedListing);
  const workplaceLocation = useSearchStore((state) => state.workplaceLocation);
  const isPickingWorkplace = useSearchStore((state) => state.isPickingWorkplace);
  const isPickingNeighborhood = useSearchStore((state) => state.isPickingNeighborhood);
  const restoreBounds = useSearchStore((state) => state.restoreBounds);
  const setFilters = useSearchStore((state) => state.setFilters);

  const mapRef = useRef<L.Map | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(timer);
  }, [notice]);

  // Map-explore plots every match (mapPoints), not just the loaded page, so
  // the cluster badges add up to the count above the feed. The ranked modes
  // plot the ranked results themselves, since there the match score is the
  // whole point of the pin and every match is already on the page.
  const isExploring = mode === "map";
  const positions = useMemo(() => {
    const index = new Map<string, [number, number]>();
    for (const point of mapPoints) index.set(point.id, [point.lat, point.lon]);
    for (const listing of [...tier1Results, ...tier2Results]) {
      index.set(listing.id, [listing.lat, listing.lon]);
    }
    return index;
  }, [mapPoints, tier1Results, tier2Results]);

  // Which pins the feed is showing a card for (see SelectedListingAction).
  const cardIds = useMemo(() => {
    const ids = new Set([...tier1Results, ...tier2Results].map((listing) => listing.id));
    if (focusedListing) ids.add(focusedListing.id);
    return ids;
  }, [tier1Results, tier2Results, focusedListing]);

  /** Puts the map back on the rectangle the search was run against -- the
   * same one, to the corner, not an approximation of it. Because the viewport
   * was never re-read while a property was in focus, the results underneath
   * are still the ones this box produced, so nothing is re-fetched. */
  const restoreSearchArea = useCallback(() => {
    const map = mapRef.current;
    if (!map || !restoreBounds) return;
    beginProgrammaticMove(0.7);
    map.flyToBounds(
      L.latLngBounds(
        [restoreBounds.min_lat, restoreBounds.min_lon],
        [restoreBounds.max_lat, restoreBounds.max_lon],
      ),
      { duration: 0.7 },
    );
    setFilters({ restoreBounds: null, selectedListingId: null });
  }, [restoreBounds, setFilters]);

  const cursor = isPickingWorkplace || isPickingNeighborhood ? "cursor-crosshair" : "";

  return (
    <div className="relative h-full w-full">
      <MapContainer
        // The provider credit is dropped at the user's request; the basemap's
        // attribution is kept on the TileLayer for anyone reading the source.
        attributionControl={false}
        ref={mapRef}
        center={TEHRAN_CENTER}
        zoom={DEFAULT_ZOOM}
        maxZoom={MAX_ZOOM}
        minZoom={MIN_ZOOM}
        maxBounds={TEHRAN_MAX_BOUNDS}
        maxBoundsViscosity={1}
        zoomSnap={ZOOM_SNAP}
        zoomDelta={ZOOM_DELTA}
        wheelPxPerZoomLevel={WHEEL_PX_PER_ZOOM_LEVEL}
        wheelDebounceTime={WHEEL_DEBOUNCE_MS}
        className={`h-full w-full ${cursor}`}
        scrollWheelZoom
      >
        <VectorBaseLayer />

        <ResizeSync />
        <BBoxSync />
        <FocusedListingFly points={positions} />
        <WorkplacePicker />
        <NeighborhoodMapPicker onNotice={setNotice} />
        <SearchAreaOverlay />
        <NeighborhoodLabels />
        <CongestionZones />
        <MetroStations />

        {/* The workplace is a pin and nothing more. A reachability wash used to
            be drawn around it, but the travel times behind it are straight-line
            estimates -- painting them as a hard boundary on the map claimed a
            precision the data does not have. How much reachability counts is now
            a weight in the ranking (see the panel's اهمیت دسترسی dial). */}
        {workplaceLocation && (
          <Marker position={[workplaceLocation.lat, workplaceLocation.lon]} icon={workplaceIcon()}>
            <Popup>
              <div className="text-right text-xs">
                <p className="font-semibold">{workplaceLocation.name || "محل کار"}</p>
              </div>
            </Popup>
          </Marker>
        )}

        {isExploring ? (
          // The grouping is the server's (app/search/map_clusters.py): the
          // browser draws what it is given instead of re-clustering thousands
          // of markers on every pan, which is what made map-explore stall.
          <>
            {mapClusters.map((cluster, index) => (
              <ClusterBadge key={`c-${index}-${cluster.count}`} cluster={cluster} />
            ))}
            {mapPoints.map((point) => (
              <MapPointMarker key={point.id} point={point} />
            ))}
          </>
        ) : (
          <>
            {tier1Results.map((listing) => (
              <ListingMarker key={listing.id} listing={listing} />
            ))}
            {tier2Results.map((listing) => (
              <ListingMarker key={listing.id} listing={listing} />
            ))}
          </>
        )}

        <SelectedListingAction positions={positions} cardIds={cardIds} />
      </MapContainer>

      {restoreBounds && (
        <button
          type="button"
          onClick={restoreSearchArea}
          className="absolute bottom-20 left-1/2 z-[900] -translate-x-1/2 rounded-full bg-slate-900/90 lg:bottom-5 px-4 py-2 text-xs font-medium text-white shadow-lg backdrop-blur transition hover:bg-slate-900"
        >
          بازگشت به محدوده جستجو
        </button>
      )}

      {notice && (
        <div className="pointer-events-none absolute top-4 left-1/2 z-[900] w-max max-w-[85%] -translate-x-1/2 rounded-full bg-white/95 px-4 py-2 text-center text-xs font-medium text-slate-700 shadow-lg ring-1 ring-slate-900/5">
          {notice}
        </div>
      )}
    </div>
  );
}
