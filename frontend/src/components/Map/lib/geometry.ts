import type { LatLngExpression } from "leaflet";

import type { GeoJSONGeometry } from "@/types";

/**
 * GeoJSON rings ([lon, lat]) converted to Leaflet rings ([lat, lon]).
 *
 * This exists because react-leaflet's `<GeoJSON>` reads its `data` only when
 * the layer is constructed, so changing the shape means remounting it by
 * `key` -- and under React 18 StrictMode a remount double-invokes the effect,
 * leaving one of the two Leaflet layers attached to the map with nothing left
 * holding a reference to remove it. The stale outline then stays on screen
 * forever. `<Polygon positions={...}>` takes its geometry as a reactive prop
 * and updates in place, so no remount and no leak.
 *
 * With `outerOnly`, interior rings are dropped: a dimming mask wants to know
 * which areas are "in", and a hole inside a hole would render as a dimmed
 * island in the middle of the search area.
 */
export function toLeafletRings(geometry: GeoJSONGeometry, outerOnly = false): LatLngExpression[][] {
  const polygons: number[][][][] =
    geometry.type === "Polygon" ? [geometry.coordinates as number[][][]] : (geometry.coordinates as number[][][][]);

  return polygons.flatMap((polygon) => {
    const rings = outerOnly ? polygon.slice(0, 1) : polygon;
    return rings
      .filter((ring) => ring.length > 0)
      .map((ring) => ring.map(([lon, lat]) => [lat, lon] as LatLngExpression));
  });
}
