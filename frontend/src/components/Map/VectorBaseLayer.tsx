"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useEffect } from "react";
import L from "leaflet";
import { getRTLTextPluginStatus, getWorkerUrl, setRTLTextPlugin, setWorkerUrl } from "maplibre-gl";
import { useMap } from "react-leaflet";

import "@maplibre/maplibre-gl-leaflet";

import { BASEMAP_ATTRIBUTION, divarMapStyle } from "./lib/divarMapStyle";

/** Copied out of node_modules at pre(dev|build) time -- see
 * scripts/copy-map-assets.mjs for why each of these has to be a real URL
 * instead of a bundled import. */
const VENDOR_DIR = "/vendor/maplibre";
const WORKER_URL = `${VENDOR_DIR}/maplibre-gl-worker.mjs`;
const RTL_PLUGIN_URL = `${VENDOR_DIR}/mapbox-gl-rtl-text.js`;

/** Absolute: both of these are consumed from inside MapLibre's worker, whose
 * base URL is not the page's, so root-relative paths don't resolve there. */
function absolute(path: string): string {
  return new URL(path, window.location.origin).toString();
}

/**
 * MapLibre finds its own worker relative to `import.meta.url`, which webpack
 * rewrites during the Next build. The worker then loads nothing, answers
 * nothing, and -- because it never errors -- leaves every tile stuck in
 * "loading" against a blank map. Pointing it at the self-hosted copy instead
 * removes the guess entirely.
 */
function ensureWorkerUrl() {
  if (getWorkerUrl()) return;
  setWorkerUrl(absolute(WORKER_URL));
}

/** Arabic-script text arrives from the tiles as unshaped logical-order code
 * points; without this plugin MapLibre renders Persian labels letter-by-letter,
 * disconnected and left-to-right. Self-hosted rather than pulled from a CDN so
 * the map keeps working offline and loads no third-party script at runtime. */
function ensureRtlTextPlugin() {
  if (getRTLTextPluginStatus() !== "unavailable") return;
  // Not lazy: labels are Persian everywhere on this map, so there is no first
  // paint worth showing before the plugin lands.
  setRTLTextPlugin(absolute(RTL_PLUGIN_URL), false).catch(() => {
    // A missing plugin degrades Persian label shaping but leaves the map
    // usable; nothing here should be able to take the map down.
  });
}

/**
 * The basemap: OpenFreeMap vector tiles rendered through MapLibre GL, mounted
 * inside the existing Leaflet map via maplibre-gl-leaflet.
 *
 * Rendering the vector basemap *inside* Leaflet (rather than migrating the
 * whole map to MapLibre) keeps every overlay this app already has --
 * react-leaflet markers, marker clustering, the isochrone and congestion-zone
 * GeoJSON layers, the workplace picker, bbox sync -- working untouched. Only
 * the tile layer changes.
 */
export default function VectorBaseLayer() {
  const map = useMap();

  useEffect(() => {
    ensureWorkerUrl();
    ensureRtlTextPlugin();

    const layer = L.maplibreGL({ style: divarMapStyle });
    layer.addTo(map);
    // maplibre-gl-leaflet's options don't carry Leaflet's `attribution`, so
    // OSM/OpenFreeMap credit (required by both) is registered directly.
    map.attributionControl?.addAttribution(BASEMAP_ATTRIBUTION);

    return () => {
      map.attributionControl?.removeAttribution(BASEMAP_ATTRIBUTION);
      map.removeLayer(layer);
    };
  }, [map]);

  return null;
}
