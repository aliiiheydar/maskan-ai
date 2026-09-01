"use client";

import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { Circle, MapContainer, Marker } from "react-leaflet";

import VectorBaseLayer from "@/components/Map/VectorBaseLayer";
import type { Listing } from "@/types";

/** How far the reader may roam around the property.
 *
 * This map answers one question -- "where is this, and what is around it?" --
 * so it is deliberately *partially* zoomable rather than a second copy of the
 * search map: the view is pinned to a small box around the pin, the zoom
 * range covers street level to about a neighborhood, and the wheel is left
 * alone so scrolling the page past the map does not zoom it instead.
 */
const MIN_ZOOM = 13;
const MAX_ZOOM = 18;
const DEFAULT_ZOOM = 16;
/** Roughly 2.2km north-south, the same east-west at Tehran's latitude. */
const PAN_HALF_SPAN_LAT = 0.02;
const PAN_HALF_SPAN_LON = 0.025;

const ACCENT = "#0f766e";
/** What a blurred advert is drawn as when it does not say how blurred it is.
 * Divar's own fuzzed pins sit in this range. */
const DEFAULT_FUZZY_RADIUS_METERS = 350;

function propertyIcon() {
  return L.divIcon({
    className: "",
    html: `<span style="
      display:block;width:20px;height:20px;border-radius:9999px;
      background:${ACCENT};border:3px solid white;
      box-shadow:0 0 0 2px rgba(15,23,42,.25), 0 2px 6px rgba(0,0,0,.35);
    "></span>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

/**
 * The property on a map, shown as precisely as the advert actually allows.
 *
 * An exact address is drawn as a pin. An advert that only publishes a fuzzed
 * location is drawn as a circle around its centre instead -- never as a pin,
 * which would claim a precision the data does not have. Which of the two the
 * reader is looking at is stated in the caption above the map, not left to be
 * inferred from the shape.
 */
export default function ListingLocationMap({ listing }: { listing: Listing }) {
  const center: [number, number] = [listing.lat, listing.lon];
  const isApproximate = listing.location_precision === "FUZZY" || listing.location_precision === "NEIGHBORHOOD";
  const radius = listing.location_radius_meters ?? DEFAULT_FUZZY_RADIUS_METERS;

  return (
    <MapContainer
      attributionControl={false}
      center={center}
      zoom={isApproximate ? DEFAULT_ZOOM - 1 : DEFAULT_ZOOM}
      minZoom={MIN_ZOOM}
      maxZoom={MAX_ZOOM}
      maxBounds={[
        [center[0] - PAN_HALF_SPAN_LAT, center[1] - PAN_HALF_SPAN_LON],
        [center[0] + PAN_HALF_SPAN_LAT, center[1] + PAN_HALF_SPAN_LON],
      ]}
      maxBoundsViscosity={1}
      scrollWheelZoom={false}
      className="h-full w-full"
    >
      <VectorBaseLayer />
      {isApproximate ? (
        <Circle
          center={center}
          radius={radius}
          pathOptions={{ color: ACCENT, weight: 2, fillColor: ACCENT, fillOpacity: 0.12 }}
        />
      ) : (
        <Marker position={center} icon={propertyIcon()} />
      )}
    </MapContainer>
  );
}
