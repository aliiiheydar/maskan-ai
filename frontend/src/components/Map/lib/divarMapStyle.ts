import type { DataDrivenPropertyValueSpecification, ExpressionSpecification, StyleSpecification } from "maplibre-gl";

/**
 * A minimal, Divar-like basemap style (see divar-map.png at the repo root).
 *
 * Divar's map is not a public product -- there is no open-source style that
 * matches it off the shelf. It is, however, plain OpenStreetMap data rendered
 * through a deliberately quiet custom style: a near-white land fill, sage
 * parks, white local streets, and one strong accent -- blue-grey highways --
 * with small grey Persian labels and nothing else competing for attention.
 * That is reproducible on open vector tiles, which is what this style does.
 *
 * Tiles come from OpenFreeMap (https://openfreemap.org): a free, no-API-key,
 * no-rate-limit public planet built from OSM with the OpenMapTiles schema.
 * This replaces the CartoDB Voyager raster tiles the map used before, which
 * had started stamping "API KEY REQUIRED" watermarks across every tile.
 *
 * Vector tiles (rather than another raster provider) are what make the Divar
 * look reachable at all: colors, road widths, label language, and which
 * features exist per zoom are all decided here on the client, so the map can
 * be tuned to the app instead of being accepted as-shipped.
 */

const OPENFREEMAP_TILEJSON = "https://tiles.openfreemap.org/planet";
const OPENFREEMAP_GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";

export const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://openfreemap.org">OpenFreeMap</a>';

/** Persian-first labels: OSM's `name:fa` where mappers supplied it, otherwise
 * the local `name` (which in Tehran is itself usually Persian). */
const PERSIAN_LABEL: DataDrivenPropertyValueSpecification<string> = [
  "coalesce",
  ["get", "name:fa"],
  ["get", "name"],
];

/** The one script in the tiles' glyph set that covers Persian. */
const LABEL_FONT = ["Noto Sans Regular"];

const PALETTE = {
  // Sampled straight off divar-map-screenshots/2,3,5.png rather than guessed:
  // Divar draws local streets and alleys in flat grey and reserves the
  // blue-grey for motorways and trunk roads, so the important routes are the
  // only thing on the map with a hue.
  land: "#f7f8fa",
  residential: "#f2f4f6",
  park: "#c3eed4",
  wood: "#c3eed4",
  // Sampled off divar-map-screenshots/1.png (the دریاچهٔ چیتگر body): Divar's
  // water is a bright, clearly-blue fill, not the pale blue-grey wash this
  // style used to draw -- on a map whose land is near-white, a desaturated
  // water reads as just another patch of ground.
  water: "#99d6ff",
  waterway: "#7ac6f7",
  building: "#eceef0",
  // The signature Divar accent: highways are the only saturated thing on the
  // map, in a desaturated steel blue.
  motorway: "#afc6df",
  motorwayCasing: "#93bcd8",
  trunk: "#bfd2e5",
  trunkCasing: "#a3c0da",
  majorRoad: "#d8dfe1",
  majorRoadCasing: "#cbd4d7",
  minorRoad: "#d8dfe1",
  minorRoadCasing: "#d0d8da",
  boundary: "#c3c6c9",
  cityBoundary: "#9ba1a7",
  // Divar's labels are noticeably darker and larger than a typical basemap's
  // (see divar-map-screenshots/): the street network is drained of color
  // precisely so the names can carry the map, which only works if they are
  // strong enough to read at a glance.
  placeLabel: "#3f4753",
  minorPlaceLabel: "#5b6472",
  majorRoadLabel: "#54606e",
  roadLabel: "#6b7684",
  waterLabel: "#3f88b5",
  labelHalo: "#ffffff",
};

const isPolygon: ExpressionSpecification = ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false];
const isLine: ExpressionSpecification = ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false];

const MINOR_CLASSES: ExpressionSpecification = ["match", ["get", "class"], ["minor", "service", "track"], true, false];
const MAJOR_CLASSES: ExpressionSpecification = [
  "match",
  ["get", "class"],
  ["primary", "secondary", "tertiary"],
  true,
  false,
];

export const divarMapStyle: StyleSpecification = {
  version: 8,
  name: "Maskan Minimal (Divar-inspired)",
  glyphs: OPENFREEMAP_GLYPHS,
  sources: {
    openmaptiles: { type: "vector", url: OPENFREEMAP_TILEJSON },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": PALETTE.land } },

    // --- Land cover -------------------------------------------------------
    {
      id: "landuse-residential",
      type: "fill",
      source: "openmaptiles",
      "source-layer": "landuse",
      maxzoom: 16,
      filter: ["all", isPolygon, ["==", ["get", "class"], "residential"]],
      paint: { "fill-color": PALETTE.residential },
    },
    {
      id: "park",
      type: "fill",
      source: "openmaptiles",
      "source-layer": "park",
      filter: isPolygon,
      paint: { "fill-color": PALETTE.park },
    },
    {
      id: "wood",
      type: "fill",
      source: "openmaptiles",
      "source-layer": "landcover",
      minzoom: 10,
      filter: ["all", isPolygon, ["match", ["get", "class"], ["wood", "grass"], true, false]],
      paint: { "fill-color": PALETTE.wood, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 10, 0, 12, 1] },
    },
    {
      id: "water",
      type: "fill",
      source: "openmaptiles",
      "source-layer": "water",
      filter: ["all", isPolygon, ["!=", ["get", "brunnel"], "tunnel"]],
      paint: { "fill-color": PALETTE.water, "fill-antialias": true },
    },
    {
      id: "waterway",
      type: "line",
      source: "openmaptiles",
      "source-layer": "waterway",
      filter: isLine,
      paint: { "line-color": PALETTE.waterway, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.6, 16, 2.4] },
    },
    // Buildings stay out of the way entirely until street level, and even then
    // are barely a shade off the land -- Divar shows footprints as texture, not
    // as content.
    {
      id: "building",
      type: "fill",
      source: "openmaptiles",
      "source-layer": "building",
      minzoom: 15,
      paint: {
        "fill-color": PALETTE.building,
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 15, 0, 16.5, 1],
      },
    },

    // --- Road network -----------------------------------------------------
    // Every road class is casing + inner fill so the network reads as ribbons
    // rather than hairlines, which is what keeps the map legible once all the
    // color has been drained out of it.
    {
      id: "road-minor-casing",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 13,
      filter: ["all", isLine, MINOR_CLASSES],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.minorRoadCasing,
        "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 13, 2.2, 20, 22],
      },
    },
    {
      id: "road-minor",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 13,
      filter: ["all", isLine, MINOR_CLASSES],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.minorRoad,
        "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 13, 1, 20, 18],
      },
    },
    {
      id: "road-major-casing",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 10,
      filter: ["all", isLine, MAJOR_CLASSES],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.majorRoadCasing,
        "line-width": ["interpolate", ["exponential", 1.35], ["zoom"], 10, 2, 14, 5, 20, 26],
      },
    },
    {
      id: "road-major",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 10,
      filter: ["all", isLine, MAJOR_CLASSES],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.majorRoad,
        "line-width": ["interpolate", ["exponential", 1.35], ["zoom"], 10, 0.8, 14, 3.2, 20, 22],
      },
    },
    {
      id: "road-trunk-casing",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 8,
      filter: ["all", isLine, ["==", ["get", "class"], "trunk"]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.trunkCasing,
        "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 8, 1.4, 12, 3.6, 20, 28],
      },
    },
    {
      id: "road-trunk",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 8,
      filter: ["all", isLine, ["==", ["get", "class"], "trunk"]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.trunk,
        "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 8, 0.6, 12, 2.2, 20, 22],
      },
    },
    {
      id: "road-motorway-casing",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 6,
      filter: ["all", isLine, ["==", ["get", "class"], "motorway"]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.motorwayCasing,
        "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 8, 1.8, 12, 4.6, 20, 32],
      },
    },
    {
      id: "road-motorway",
      type: "line",
      source: "openmaptiles",
      "source-layer": "transportation",
      minzoom: 6,
      filter: ["all", isLine, ["==", ["get", "class"], "motorway"]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.motorway,
        "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 8, 1, 12, 3, 20, 26],
      },
    },

    // --- Administrative boundaries ---------------------------------------
    // Tehran's municipal districts (مناطق) are admin_level 6-8 here; they are
    // the dashed grey outlines on Divar's map, drawn under the labels.
    {
      id: "boundary-district",
      type: "line",
      source: "openmaptiles",
      "source-layer": "boundary",
      minzoom: 9,
      filter: ["all", [">=", ["get", "admin_level"], 5], ["!=", ["get", "maritime"], 1]],
      paint: {
        "line-color": PALETTE.boundary,
        "line-dasharray": [2, 2],
        "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.6, 14, 1.4],
      },
    },
    {
      id: "boundary-city",
      type: "line",
      source: "openmaptiles",
      "source-layer": "boundary",
      filter: ["all", [">=", ["get", "admin_level"], 2], ["<=", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.cityBoundary,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.8, 12, 2],
      },
    },

    // --- Labels -----------------------------------------------------------
    {
      id: "label-water",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "water_name",
      minzoom: 10,
      layout: {
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-size": 11,
        "text-max-width": 8,
      },
      paint: { "text-color": PALETTE.waterLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1 },
    },
    // Road labels arrive in three waves, by how important the road is. The
    // reference screenshots show highway names (بزرگراه ...) already legible
    // at a whole-city zoom, arterials appearing a couple of steps later, and
    // side streets only at walking zoom -- so what a name *is* decides when it
    // shows up, and the more important it is, the earlier and larger it is.
    {
      id: "label-road-highway",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "transportation_name",
      minzoom: 9,
      filter: ["match", ["get", "class"], ["motorway", "trunk"], true, false],
      layout: {
        "symbol-placement": "line",
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-rotation-alignment": "map",
        "text-size": ["interpolate", ["linear"], ["zoom"], 9, 11, 12, 12.5, 16, 14],
        "symbol-spacing": 300,
      },
      paint: { "text-color": PALETTE.majorRoadLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1.6 },
    },
    {
      id: "label-road-major",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "transportation_name",
      minzoom: 11,
      filter: ["match", ["get", "class"], ["primary", "secondary"], true, false],
      layout: {
        "symbol-placement": "line",
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-rotation-alignment": "map",
        "text-size": ["interpolate", ["linear"], ["zoom"], 11, 10.5, 14, 12, 17, 13],
      },
      paint: { "text-color": PALETTE.majorRoadLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1.5 },
    },
    {
      id: "label-road-minor",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "transportation_name",
      minzoom: 13.5,
      filter: ["match", ["get", "class"], ["tertiary", "minor"], true, false],
      layout: {
        "symbol-placement": "line",
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-rotation-alignment": "map",
        "text-size": ["interpolate", ["linear"], ["zoom"], 13.5, 10, 17, 12],
      },
      paint: { "text-color": PALETTE.roadLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1.4 },
    },
    // No محله labels from the basemap: the app draws its own from the same
    // polygons the neighborhood filter runs on (see NeighborhoodLabels), and
    // OSM's place points sit at slightly different coordinates, so leaving
    // both on printed every neighborhood name twice once the tiles reached
    // their own label zoom. The app's layer wins because it is the one whose
    // names match the filter chips.
    {
      id: "label-settlement",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "place",
      maxzoom: 14,
      filter: ["match", ["get", "class"], ["city", "town", "village"], true, false],
      layout: {
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-max-width": 8,
        "text-size": ["interpolate", ["linear"], ["zoom"], 6, 13, 12, 17],
      },
      paint: { "text-color": PALETTE.placeLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1.6 },
    },
    {
      id: "label-place-other",
      type: "symbol",
      source: "openmaptiles",
      "source-layer": "place",
      minzoom: 13,
      filter: ["match", ["get", "class"], ["city", "town", "village", "suburb", "neighbourhood", "quarter"], false, true],
      layout: {
        "text-field": PERSIAN_LABEL,
        "text-font": LABEL_FONT,
        "text-max-width": 8,
        "text-size": 11,
      },
      paint: { "text-color": PALETTE.minorPlaceLabel, "text-halo-color": PALETTE.labelHalo, "text-halo-width": 1.4 },
    },
  ],
};
