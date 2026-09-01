"""Commute-time reachability geometry for map visualization.

For transit mode this asks app.spatial.routing how long it takes to reach
every station in the city from the query point -- the same leg-by-leg
walk/wait/ride/change model that scores commutes during ranking -- and draws
a walk-buffer around each station the budget still has time left at. Because
both surfaces read from one router, the shape on the map and the commute
score on a listing can never tell the user two different things.

Walk and drive modes stay a single radius circle: there is no road-network
router integrated (see CLAUDE.md's documented MVP tradeoff), but they are
sized with the same speed constants the ranking uses.

All of those circles are buffered and unioned into a single polygon before
being returned, instead of handing back ~130 raw overlapping circles --
rendering that many stacked fills was flooding the map around the workplace
pin. Buffering happens in a small local equirectangular projection (meters,
centered on the query point) rather than in raw lon/lat degrees, since a
degree of longitude is ~19% shorter than a degree of latitude at Tehran's
~35.7N -- buffering directly in degrees would produce east-west-squashed
ellipses instead of circles.

The traversal runs once per workplace/mode change for visualization, not
once per candidate listing, and the router memoises it besides.
"""

import math
from dataclasses import dataclass
from typing import Callable

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from app.core import constants
from app.spatial import routing

_METERS_PER_DEGREE_LAT = 111_320.0
_ISOCHRONE_SIMPLIFY_TOLERANCE_METERS = 25.0


@dataclass
class _ReachableStation:
    lat: float
    lon: float
    radius_meters: float


def _local_projection(lat0: float, lon0: float) -> tuple[Callable, Callable]:
    """Forward/inverse (lon, lat) <-> local-meters transforms for a small
    equirectangular projection centered on (lat0, lon0). Accurate enough for
    Tehran's ~40km extent; not meant for anything beyond city-scale."""
    meters_per_degree_lon = _METERS_PER_DEGREE_LAT * math.cos(math.radians(lat0))

    def forward(lon: float, lat: float) -> tuple[float, float]:
        return (lon - lon0) * meters_per_degree_lon, (lat - lat0) * _METERS_PER_DEGREE_LAT

    def inverse(x: float, y: float) -> tuple[float, float]:
        return x / meters_per_degree_lon + lon0, y / _METERS_PER_DEGREE_LAT + lat0

    return forward, inverse


def _union_buffered_points(lat0: float, lon0: float, stations: list[_ReachableStation]) -> BaseGeometry:
    forward, inverse = _local_projection(lat0, lon0)
    circles = [Point(*forward(s.lon, s.lat)).buffer(s.radius_meters) for s in stations]
    merged = unary_union(circles).simplify(_ISOCHRONE_SIMPLIFY_TOLERANCE_METERS)
    return transform(lambda x, y: inverse(x, y), merged)


def _reachable_transit_stations(lat: float, lon: float, budget_mins: float) -> list[_ReachableStation]:
    """Every station reachable from (lat, lon) inside the time budget, each
    with the walk-buffer its own leftover time buys.

    The times come from app.spatial.routing, the same leg-by-leg walk/wait/
    ride/change model the ranking scores commutes with, so the shape drawn on
    the map and the score attached to a listing can never disagree. A station
    reached early in the budget gets a bigger "you can also walk from here"
    buffer than one reached right at the edge of what is affordable.
    """
    stations: list[_ReachableStation] = []
    for station_id, arrival_mins in routing.arrival_times(lat, lon).items():
        leftover = budget_mins - arrival_mins
        if leftover <= 0:
            continue
        node = routing.NETWORK.nodes[station_id]
        stations.append(
            _ReachableStation(
                lat=node["lat"], lon=node["lon"], radius_meters=leftover * constants.WALK_SPEED_MPM
            )
        )
    return stations


def compute_isochrone_geometry(lat: float, lon: float, max_minutes: float, mode: str) -> BaseGeometry | None:
    """A single polygon (or multipolygon) approximating everywhere reachable
    from (lat, lon) within max_minutes for the given commute mode. None if
    nothing is reachable (e.g. max_minutes <= 0)."""
    if max_minutes <= 0:
        return None

    if mode == "walk":
        return _union_buffered_points(lat, lon, [_ReachableStation(lat, lon, max_minutes * constants.WALK_SPEED_MPM)])

    if mode == "drive":
        drive_speed_mpm = constants.AVG_DRIVE_SPEED_KMH * 1000.0 / 60.0
        return _union_buffered_points(lat, lon, [_ReachableStation(lat, lon, max_minutes * drive_speed_mpm)])

    if mode == "transit":
        # Anyone within direct walking distance is reachable regardless of
        # transit, plus everywhere reachable by riding the station graph.
        direct_walk = _ReachableStation(lat, lon, max_minutes * constants.WALK_SPEED_MPM)
        stations = [direct_walk, *_reachable_transit_stations(lat, lon, max_minutes)]
        return _union_buffered_points(lat, lon, stations)

    raise ValueError(f"Unknown commute mode: {mode!r}. Expected 'walk', 'drive', or 'transit'.")
