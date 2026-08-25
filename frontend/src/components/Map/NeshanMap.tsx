"use client";

// Neshan's Web SDK requires a paid API key that isn't configured in this repo
// (see .env.example -- only OpenRouter keys are provisioned). Leaflet + OSM
// tiles is used instead, per the CLAUDE.md-approved "Leaflet / MapLibre /
// Neshan Web SDK" options. To switch to Neshan tiles later, swap the
// TileLayer url below for Neshan's tile endpoint and pass an API key via
// NEXT_PUBLIC_NESHAN_API_KEY -- everything else (markers, bbox sync,
// isochrone circle) is tile-provider agnostic.
import "leaflet/dist/leaflet.css";

import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import { Circle, MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";

import { useSearchStore } from "@/store/useSearchStore";
import type { ListingResult } from "@/types";

const TEHRAN_CENTER: [number, number] = [35.6997, 51.338];
const DEFAULT_ZOOM = 12;
const BBOX_DEBOUNCE_MS = 300;
const WALK_SPEED_KM_PER_MIN = 0.08; // 80 m/min, matches backend app/core/config.py

function pinIcon(tier: 1 | 2, isPulsing: boolean) {
  const color = tier === 1 ? "#15803d" : "#2563eb";
  const size = isPulsing ? 30 : 22;
  return L.divIcon({
    className: "",
    html: `<span style="
      display:block;width:${size}px;height:${size}px;border-radius:9999px;
      background:${color};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.4);
      transition:width .2s,height .2s;
      ${isPulsing ? "animation:maskan-pulse 1s ease-in-out infinite;" : ""}
    "></span>
    <style>
      @keyframes maskan-pulse { 0%,100%{opacity:1;} 50%{opacity:.55;} }
    </style>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

/** Reports pan/zoom bounds back to the shared store, debounced, for Zero-Query
 * map-mode search (docs/FRONTEND_STATE.md SS3 "Viewport Debouncing"). */
function BBoxSync() {
  const mode = useSearchStore((state) => state.mode);
  const setFilters = useSearchStore((state) => state.setFilters);
  const runSearch = useSearchStore((state) => state.runSearch);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const map = useMapEvents({
    moveend: () => {
      if (mode !== "map") return;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        const bounds = map.getBounds();
        setFilters({
          mapBBox: {
            minLat: bounds.getSouth(),
            minLon: bounds.getWest(),
            maxLat: bounds.getNorth(),
            maxLon: bounds.getEast(),
          },
        });
        runSearch();
      }, BBOX_DEBOUNCE_MS);
    },
  });

  return null;
}

/** Recenters + pulses the map on the listing a hovered/selected card points at. */
function FocusedListingFly({ listings }: { listings: ListingResult[] }) {
  const map = useMap();
  const hoveredListingId = useSearchStore((state) => state.hoveredListingId);
  const selectedListingId = useSearchStore((state) => state.selectedListingId);

  useEffect(() => {
    const focusId = hoveredListingId ?? selectedListingId;
    if (!focusId) return;
    const listing = listings.find((l) => l.id === focusId);
    if (listing) {
      map.flyTo([listing.lat, listing.lon], Math.max(map.getZoom(), 14), { duration: 0.5 });
    }
  }, [hoveredListingId, selectedListingId, listings, map]);

  return null;
}

export default function NeshanMap() {
  const tier1Results = useSearchStore((state) => state.tier1Results);
  const tier2Results = useSearchStore((state) => state.tier2Results);
  const hoveredListingId = useSearchStore((state) => state.hoveredListingId);
  const selectedListingId = useSearchStore((state) => state.selectedListingId);
  const setSelectedListingId = useSearchStore((state) => state.setSelectedListingId);
  const setFilters = useSearchStore((state) => state.setFilters);
  const workplaceLocation = useSearchStore((state) => state.workplaceLocation);
  const maxCommuteMins = useSearchStore((state) => state.maxCommuteMins);

  const allListings = useMemo(() => [...tier1Results, ...tier2Results], [tier1Results, tier2Results]);

  // Approximate commute isochrone: a radius circle around the workplace,
  // sized by walk-equivalent distance for maxCommuteMins. This is a coarse
  // stand-in for a true multimodal isochrone polygon -- the API only exposes
  // point-to-point commute estimates (docs/ALGORITHMS.md S_commute), not a
  // precomputed reachability polygon.
  const isochroneRadiusMeters = maxCommuteMins * WALK_SPEED_KM_PER_MIN * 1000 * 3; // *3 as a transit/drive speed-up factor

  return (
    <MapContainer center={TEHRAN_CENTER} zoom={DEFAULT_ZOOM} className="h-full w-full" scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <BBoxSync />
      <FocusedListingFly listings={allListings} />

      {workplaceLocation && (
        <Circle
          center={[workplaceLocation.lat, workplaceLocation.lon]}
          radius={isochroneRadiusMeters}
          pathOptions={{ color: "#b45309", fillColor: "#b45309", fillOpacity: 0.08, weight: 1.5, dashArray: "6 4" }}
        />
      )}

      {allListings.map((listing) => (
        <Marker
          key={listing.id}
          position={[listing.lat, listing.lon]}
          icon={pinIcon(listing.tier, listing.id === hoveredListingId || listing.id === selectedListingId)}
          eventHandlers={{
            click: () => {
              setSelectedListingId(listing.id);
              if (listing.tier === 2) setFilters({ showTier2: true });
            },
          }}
        >
          <Popup>
            <div className="text-right text-xs">
              <p className="font-semibold">{listing.title}</p>
              <p className="text-slate-500">{listing.neighborhood}</p>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
