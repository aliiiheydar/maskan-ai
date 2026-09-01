"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Polygon, useMap } from "react-leaflet";
import L from "leaflet";
import type { LatLngExpression } from "leaflet";

import { getCityBoundary, getSearchArea } from "@/lib/api";
import { useSearchStore } from "@/store/useSearchStore";
import type { GeoJSONGeometry } from "@/types";
import { toLeafletRings } from "./lib/geometry";
import { whenMapIsVisible } from "./lib/visibility";

/** Everything outside the search area is dimmed by a single polygon that
 * covers the world and has the search area punched out of it as holes.
 * Leaflet fills paths with the even-odd rule, so nested rings become holes
 * regardless of their winding. */
const WORLD_RING: LatLngExpression[] = [
  [-89, -179],
  [-89, 179],
  [89, 179],
  [89, -179],
];

const BORDER_COLOR = "#111827";
const DIM_COLOR = "#94a3b8";

/**
 * The boundary of what is currently being searched: all of Tehran by default,
 * or the selected neighborhoods once any are chosen. The area inside keeps the
 * normal basemap; everything outside is washed light grey, and the boundary
 * itself is a thick black line -- the same "you are searching here" language
 * Divar's map uses (see divar-map-screenshots/1.png).
 *
 * The selection is drawn as one dissolved shape rather than as a stack of
 * outlines. Two adjacent neighborhoods chosen together are one search area;
 * the line between them is how the city is subdivided, not an edge of the
 * search, so the server unions it away (GET /geo/neighborhoods/area) and what
 * is left is the outline of the area as the user actually drew it.
 */
export default function SearchAreaOverlay() {
  const map = useMap();
  const mode = useSearchStore((state) => state.mode);
  const searchInViewport = useSearchStore((state) => state.searchInViewport);
  const selection = useSearchStore((state) => state.selectedNeighborhoods);
  const setFilters = useSearchStore((state) => state.setFilters);
  // Map-explore and "search this rectangle" both search the viewport, not the
  // filter panel's neighborhoods, so the outline there is always the whole
  // city -- drawing a boundary the search isn't honouring would be a lie about
  // what is being searched.
  const selectedNeighborhoods = useMemo(
    () => (mode === "map" || searchInViewport ? [] : selection),
    [mode, searchInViewport, selection],
  );
  const [cityGeometry, setCityGeometry] = useState<GeoJSONGeometry | null>(null);
  const [areaGeometry, setAreaGeometry] = useState<GeoJSONGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCityBoundary()
      .then((boundary) => {
        if (!cancelled) setCityGeometry(boundary.geometry);
      })
      .catch(() => {
        if (!cancelled) setCityGeometry(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (selectedNeighborhoods.length === 0) {
      setAreaGeometry(null);
      return;
    }
    let cancelled = false;
    getSearchArea(selectedNeighborhoods)
      .then((area) => {
        if (!cancelled) setAreaGeometry(area.geometry);
      })
      .catch(() => {
        if (!cancelled) setAreaGeometry(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNeighborhoods]);

  // Falling back to the city outline while the selected area is still in
  // flight keeps the map from flashing fully-dimmed between selections.
  const activeGeometry = useMemo(() => {
    if (selectedNeighborhoods.length > 0 && areaGeometry) return areaGeometry;
    return cityGeometry;
  }, [selectedNeighborhoods, areaGeometry, cityGeometry]);

  const areaRings = useMemo(
    () => (activeGeometry ? toLeafletRings(activeGeometry, true) : []),
    [activeGeometry],
  );

  // Choosing a neighborhood is a statement about where to look, so the map
  // goes there -- an outline the user has to hunt for on a city-wide view
  // isn't an answer. Keyed on the *fetched* area, not on the selection:
  // firing when the selection changes would frame whatever geometry was still
  // on screen (the city) a moment before the new polygon arrives. And only on
  // an actual change, so this never fights the user's own panning.
  const lastFitted = useRef<string>("");
  useEffect(() => {
    if (selectedNeighborhoods.length === 0 || !areaGeometry) {
      setFilters({ searchAreaBounds: null });
      return;
    }
    const bounds = L.latLngBounds(toLeafletRings(areaGeometry, true).flat());
    if (!bounds.isValid()) return;
    // Published for anyone who needs to come back *here* rather than to
    // wherever the map was last dragged -- see searchAreaBounds.
    setFilters({
      searchAreaBounds: {
        min_lat: bounds.getSouth(),
        min_lon: bounds.getWest(),
        max_lat: bounds.getNorth(),
        max_lon: bounds.getEast(),
      },
    });

    const signature = selectedNeighborhoods.join(",");
    if (signature === lastFitted.current) return;
    lastFitted.current = signature;

    // On a phone the map is a tab that may be hidden while the neighborhood is
    // chosen in the filter panel, and Leaflet cannot frame bounds inside a 0x0
    // container -- see whenMapIsVisible.
    return whenMapIsVisible(map, () => map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 }));
  }, [selectedNeighborhoods, areaGeometry, map, setFilters]);

  if (areaRings.length === 0) return null;

  return (
    <>
      <Polygon
        positions={[WORLD_RING, ...areaRings]}
        pathOptions={{ stroke: false, fillColor: DIM_COLOR, fillOpacity: 0.38, interactive: false }}
      />
      {/* Each ring is drawn as its own outline rather than as one multi-ring
          polygon, so the border reads as a line around each selected area. */}
      {areaRings.map((ring, index) => (
        <Polygon
          key={index}
          positions={ring}
          pathOptions={{ color: BORDER_COLOR, weight: 3, opacity: 0.9, fill: false, interactive: false }}
        />
      ))}
    </>
  );
}
