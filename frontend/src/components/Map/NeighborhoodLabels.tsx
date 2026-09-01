"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { Marker, useMap, useMapEvents } from "react-leaflet";

import { useSearchStore } from "@/store/useSearchStore";
import type { NeighborhoodSummary } from "@/types";

/**
 * A neighborhood's name appears once its polygon takes up a meaningful share
 * of the window, so the label always describes something the user can actually
 * see the extent of. Below this, the name would be pointing at a speck.
 */
const MIN_VIEWPORT_COVERAGE = 0.17;
/** Past this, the neighborhood is larger than the screen -- the user is inside
 * it and the street names have taken over, so the area label steps aside. */
const MAX_VIEWPORT_COVERAGE = 2.2;
/** Even a large polygon is not worth labelling from a country-wide zoom. */
const MIN_ZOOM = 11;
/**
 * Hysteresis. A label that is already on screen is held until it leaves a
 * band wider than the one it had to enter, and its centre is tested against
 * bounds padded outward rather than the exact viewport.
 *
 * Without this, the thresholds above sit right on the edge of the visible
 * band for whole neighborhoods at a time, and every small pan -- including
 * the ones the map makes itself when focusing a hovered card -- pushes the
 * same names across the line and back, so they blink on and off.
 */
const KEEP_COVERAGE_SLACK = 0.35;
const KEEP_BOUNDS_PADDING = 0.25;

function labelIcon(title: string) {
  return L.divIcon({
    className: "neighborhood-label",
    html: `<span>${title}</span>`,
    // Sized by its own content; an explicit iconSize would clip Persian text.
    iconSize: undefined,
  });
}

export default function NeighborhoodLabels() {
  const map = useMap();
  const catalog = useSearchStore((state) => state.neighborhoodCatalog);
  const loadNeighborhoods = useSearchStore((state) => state.loadNeighborhoods);
  const [viewport, setViewport] = useState(() => ({ bounds: map.getBounds(), zoom: map.getZoom() }));

  useEffect(() => {
    void loadNeighborhoods();
  }, [loadNeighborhoods]);

  useMapEvents({
    moveend: () => setViewport({ bounds: map.getBounds(), zoom: map.getZoom() }),
    zoomend: () => setViewport({ bounds: map.getBounds(), zoom: map.getZoom() }),
  });

  const shownKeys = useRef<Set<string>>(new Set());

  const visible = useMemo<NeighborhoodSummary[]>(() => {
    if (viewport.zoom < MIN_ZOOM || catalog.length === 0) {
      shownKeys.current = new Set();
      return [];
    }

    const { bounds } = viewport;
    const viewLat = bounds.getNorth() - bounds.getSouth();
    const viewLon = bounds.getEast() - bounds.getWest();
    if (viewLat <= 0 || viewLon <= 0) return [];

    const keptBounds = bounds.pad(KEEP_BOUNDS_PADDING);
    const previous = shownKeys.current;

    const next = catalog.filter((neighborhood) => {
      const center: [number, number] = [neighborhood.center_lat, neighborhood.center_lon];
      const wasShown = previous.has(neighborhood.key);
      if (!(wasShown ? keptBounds : bounds).contains(center)) return false;
      // The wider of the two axes decides: a long, narrow neighborhood along
      // one axis still reads as "this area fills the screen".
      const coverage = Math.max(
        (neighborhood.max_lat - neighborhood.min_lat) / viewLat,
        (neighborhood.max_lon - neighborhood.min_lon) / viewLon,
      );
      const min = wasShown ? MIN_VIEWPORT_COVERAGE * (1 - KEEP_COVERAGE_SLACK) : MIN_VIEWPORT_COVERAGE;
      const max = wasShown ? MAX_VIEWPORT_COVERAGE * (1 + KEEP_COVERAGE_SLACK) : MAX_VIEWPORT_COVERAGE;
      return coverage >= min && coverage <= max;
    });

    shownKeys.current = new Set(next.map((neighborhood) => neighborhood.key));
    return next;
  }, [catalog, viewport]);

  return (
    <>
      {visible.map((neighborhood) => (
        <Marker
          key={neighborhood.key}
          position={[neighborhood.center_lat, neighborhood.center_lon]}
          icon={labelIcon(neighborhood.title)}
          interactive={false}
          // Under every pin and outline: this is background context, not a
          // thing to click.
          zIndexOffset={-1000}
        />
      ))}
    </>
  );
}
