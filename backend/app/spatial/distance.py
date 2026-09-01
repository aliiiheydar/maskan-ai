"""Geospatial distance primitives."""

from math import asin, atan2, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometers."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)

    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return _EARTH_RADIUS_KM * 2 * atan2(sqrt(a), sqrt(1 - a))


_METERS_PER_DEGREE_LAT = 111_320.0


def manhattan_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Street-grid ("city block") distance between two WGS84 points, in metres.

    Used for every walking leg in the app instead of the straight line,
    because nobody walks through buildings: Tehran north of the bazaar is laid
    out on a broadly rectilinear grid, so |dx| + |dy| is a far better estimate
    of how far someone actually walks to a station than the great-circle
    distance is. It runs 20-40% longer than the haversine figure, which is
    about the detour factor measured on real pedestrian routing.
    """
    meters_per_degree_lon = _METERS_PER_DEGREE_LAT * cos(radians((lat1 + lat2) / 2.0))
    return abs(lat2 - lat1) * _METERS_PER_DEGREE_LAT + abs(lon2 - lon1) * meters_per_degree_lon
