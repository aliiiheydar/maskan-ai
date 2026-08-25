"""Tehran metro/BRT station graph and commute-time estimation."""

import json
from pathlib import Path

from app.core import constants
from app.spatial.distance import haversine_distance_km

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tehran_transit_nodes.json"
TRANSIT_NODES: list[dict] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def find_nearest_metro_station(lat: float, lon: float) -> tuple[dict, float, float]:
    """Return (station, distance_km, walk_time_mins) for the nearest metro station."""
    metro_nodes = [n for n in TRANSIT_NODES if n["type"] == "metro"]
    nearest = min(metro_nodes, key=lambda n: haversine_distance_km(lat, lon, n["lat"], n["lon"]))
    dist_km = haversine_distance_km(lat, lon, nearest["lat"], nearest["lon"])
    walk_mins = dist_km * 1000 / constants.WALK_SPEED_MPM
    return nearest, dist_km, walk_mins


def is_inside_tarh_terafik(lat: float, lon: float) -> bool:
    """Whether a point falls inside the (approximate) congestion-pricing zone."""
    b = constants.TARH_TERAFIK_BBOX
    return b.min_lat <= lat <= b.max_lat and b.min_lon <= lon <= b.max_lon


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
        return dist_km * 1000 / constants.WALK_SPEED_MPM

    if mode == "drive":
        minutes = dist_km / constants.AVG_DRIVE_SPEED_KMH * 60.0
        if is_inside_tarh_terafik(origin_lat, origin_lon) or is_inside_tarh_terafik(dest_lat, dest_lon):
            minutes *= constants.CONGESTION_PENALTY
        return minutes

    if mode == "transit":
        return dist_km / constants.AVG_TRANSIT_SPEED_KMH * 60.0 + constants.TRANSIT_TRANSFER_BUFFER_MINS

    raise ValueError(f"Unknown commute mode: {mode!r}. Expected 'walk', 'drive', or 'transit'.")
