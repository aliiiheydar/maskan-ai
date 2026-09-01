"""Tehran metro/BRT station graph and commute-time estimation."""

import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from app.core import constants
from app.spatial.distance import haversine_distance_km, manhattan_distance_m

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tehran_transit_nodes.json"
TRANSIT_NODES: list[dict] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))

# Real polygon boundaries for Tarh-e Terafik / Tarh-e Aloodegi, sourced from
# OpenStreetMap (relations tagged boundary=limited_traffic_zone /
# boundary=low_emission_zone for Tehran, trafficcontrol.tehran.ir). Optional:
# if this file isn't present, both zone checks fall back to the
# TARH_TERAFIK_BBOX rectangle approximation, so the app behaves identically
# either way -- dropping the file in later requires no code change.
_CONGESTION_ZONES_PATH = Path(__file__).resolve().parent.parent / "data" / "congestion_zones.geojson"

# Maps OSM's boundary tag values (real data) to our internal zone names.
_CONGESTION_ZONE_BOUNDARY_TAGS = {
    "limited_traffic_zone": "tarh_terafik",
    "low_emission_zone": "tarh_aloodegi",
}


def _load_congestion_zone_polygons() -> dict[str, BaseGeometry]:
    if not _CONGESTION_ZONES_PATH.exists():
        return {}
    geojson = json.loads(_CONGESTION_ZONES_PATH.read_text(encoding="utf-8"))
    polygons: dict[str, BaseGeometry] = {}
    for feature in geojson.get("features", []):
        boundary_tag = feature.get("properties", {}).get("boundary")
        zone_name = _CONGESTION_ZONE_BOUNDARY_TAGS.get(boundary_tag)
        if zone_name:
            polygons[zone_name] = shape(feature["geometry"])
    return polygons


_CONGESTION_ZONE_POLYGONS = _load_congestion_zone_polygons()

# Persian display labels, matching the real name/name:fa values already in
# congestion_zones.geojson -- used for the map's zone outline badges.
_CONGESTION_ZONE_LABELS = {
    "tarh_terafik": "طرح ترافیک",
    "tarh_aloodegi": "طرح کنترل آلودگی هوا",
}


def get_congestion_zones() -> list[tuple[str, str, BaseGeometry]]:
    """(zone_name, persian_label, polygon) for each loaded congestion zone,
    for map display. Empty if congestion_zones.geojson isn't present."""
    return [
        (zone_name, _CONGESTION_ZONE_LABELS[zone_name], polygon)
        for zone_name, polygon in _CONGESTION_ZONE_POLYGONS.items()
    ]


def find_nearest_metro_station(lat: float, lon: float) -> tuple[dict, float, float]:
    """Return (station, distance_km, walk_time_mins) for the nearest metro station.

    Distance and walking time are both measured on the street grid (Manhattan),
    not as the crow flies: the walk time is what the ranking scores, and a
    station 400 metres away across a block is not a five-minute walk in a
    straight line. Delegates to app.spatial.routing so there is exactly one
    definition of "how far is the metro" in the app.
    """
    from app.spatial.routing import nearest_metro_walk_minutes

    station, dist_meters, walk_mins = nearest_metro_walk_minutes(lat, lon)
    return station, dist_meters / 1000.0, walk_mins


def _is_inside_zone(lat: float, lon: float, zone_name: str) -> bool:
    """Point-in-polygon check against real GeoJSON zone data when available,
    falling back to the TARH_TERAFIK_BBOX rectangle approximation."""
    polygon = _CONGESTION_ZONE_POLYGONS.get(zone_name)
    if polygon is not None:
        return polygon.contains(Point(lon, lat))
    b = constants.TARH_TERAFIK_BBOX
    return b.min_lat <= lat <= b.max_lat and b.min_lon <= lon <= b.max_lon


def is_inside_tarh_terafik(lat: float, lon: float) -> bool:
    """Whether a point falls inside the congestion-pricing zone."""
    return _is_inside_zone(lat, lon, "tarh_terafik")


def is_inside_tarh_aloodegi(lat: float, lon: float) -> bool:
    """Whether a point falls inside the low-emission/pollution-control zone."""
    return _is_inside_zone(lat, lon, "tarh_aloodegi")


def estimate_commute_time(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    mode: str = "transit",
) -> float:
    """Estimate one-way commute time in minutes for 'walk', 'drive', or 'transit'."""
    dist_km = haversine_distance_km(origin_lat, origin_lon, dest_lat, dest_lon)

    if mode == "walk":
        return manhattan_distance_m(origin_lat, origin_lon, dest_lat, dest_lon) / constants.WALK_SPEED_MPM

    if mode == "drive":
        minutes = dist_km / constants.AVG_DRIVE_SPEED_KMH * 60.0
        if is_inside_tarh_terafik(origin_lat, origin_lon) or is_inside_tarh_terafik(dest_lat, dest_lon):
            minutes *= constants.CONGESTION_PENALTY
        return minutes

    if mode == "transit":
        # Routed over the real metro/BRT graph -- walk, wait, ride, change,
        # walk -- rather than airline distance over an average network speed.
        # See app/spatial/routing.py for the leg-by-leg cost model.
        from app.spatial.routing import transit_travel_minutes

        return transit_travel_minutes(origin_lat, origin_lon, dest_lat, dest_lon)

    raise ValueError(f"Unknown commute mode: {mode!r}. Expected 'walk', 'drive', or 'transit'.")
