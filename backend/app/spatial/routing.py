"""Point-to-point public-transport routing over the Tehran metro/BRT network.

What this replaces: a single straight-line distance divided by an average
network speed, plus a flat transfer buffer. That model could not tell a trip
along one line from a trip that crosses the city on three, and it charged the
same for a station 200 metres away as for one across a motorway.

The model here follows what a rider actually spends time on:

    walk to the station -> wait for the train -> ride N stations
      -> (change line: walk the passage -> wait again) -> ...
      -> walk from the last station to the door

Every leg is priced separately (see app/core/constants.py):

* **Riding** is flat per station hop -- 2.5 min between metro stations, 2.0
  between BRT stops. Tehran's inter-station spacing is even enough that dwell
  time, not distance, dominates the variation.
* **Waiting** is half the headway, and for the metro it is per line: line 6 at
  7.5 minutes is nearly twice line 1's 4. That difference is large enough to
  decide which of two routes is actually faster, so it cannot be averaged away.
* **Changing line inside one interchange station** costs a minute of passage
  walking, and then the new line's wait on top -- they are two different
  things and both really happen.
* **Every walking leg** -- to the first station, from the last, and between two
  stations that are not the same station (metro to BRT, or one BRT corridor to
  another) -- is Manhattan distance divided by walking speed. Nobody walks
  through buildings.

Cost model, not a timetable: it has no notion of time of day, service hours or
crowding, and it assumes the trip is symmetric in each direction.

**Performance.** A search scores every candidate listing against one
workplace, so the expensive half is done once and reused: a single Dijkstra
outward from the workplace yields the arrival time at every station in the
city (`arrival_times`, memoised on the rounded query point), after which each
listing costs one lookup over the handful of stations near it. Running a
Dijkstra per listing instead would be thousands of times the work for the
same answer.
"""

from __future__ import annotations

import heapq
import math
from functools import lru_cache
from typing import Iterable, Optional

from app.core import constants
from app.spatial.distance import manhattan_distance_m

# --------------------------------------------------------------------------
# Station index
# --------------------------------------------------------------------------

#: How far someone will walk to reach the network at all. Past ~19 minutes on
#: foot the trip stops being "take the metro" and becomes "walk"; the direct
#: walking leg, which is always considered, covers that case.
MAX_ACCESS_WALK_METERS: float = 1500.0

#: Grid cell for the station lookup, in degrees of latitude (~1.1 km). Sized so
#: that a MAX_ACCESS_WALK_METERS query is answered by the cell plus its eight
#: neighbours.
_CELL_DEG = 0.01


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / _CELL_DEG)), int(math.floor(lon / _CELL_DEG))


class _Network:
    """The station graph, built once at import.

    Nodes are (station, line) states rather than bare stations: a rider who is
    already on line 3 pays nothing to stay on it and pays the change cost to
    leave it, which a station-only graph cannot express.
    """

    def __init__(self, nodes: list[dict]) -> None:
        self.nodes = {node["id"]: node for node in nodes}
        self.grid: dict[tuple[int, int], list[str]] = {}
        for node in nodes:
            self.grid.setdefault(_cell(node["lat"], node["lon"]), []).append(node["id"])
        self.walk_transfers = self._build_walk_transfers()

    # -- construction ------------------------------------------------------

    def _build_walk_transfers(self) -> dict[str, list[tuple[str, float]]]:
        """Station pairs close enough to walk between, with the walk in minutes.

        Only pairs that are not already joined by a shared line: two stops on
        the same corridor are ridden between, not walked.
        """
        transfers: dict[str, list[tuple[str, float]]] = {}
        for station_id, node in self.nodes.items():
            neighbours: list[tuple[str, float]] = []
            for other_id in self.nearby(node["lat"], node["lon"], constants.MAX_TRANSFER_WALK_METERS):
                if other_id == station_id:
                    continue
                other = self.nodes[other_id]
                if set(node.get("lines") or ()) & set(other.get("lines") or ()):
                    continue
                meters = manhattan_distance_m(node["lat"], node["lon"], other["lat"], other["lon"])
                if meters <= constants.MAX_TRANSFER_WALK_METERS:
                    neighbours.append((other_id, meters / constants.WALK_SPEED_MPM))
            transfers[station_id] = neighbours
        return transfers

    # -- lookups -----------------------------------------------------------

    def nearby(self, lat: float, lon: float, radius_meters: float) -> list[str]:
        """Every station within radius_meters on the street grid."""
        row, col = _cell(lat, lon)
        span = int(math.ceil(radius_meters / (_CELL_DEG * 111_320.0)))
        found: list[str] = []
        for d_row in range(-span, span + 1):
            for d_col in range(-span, span + 1):
                for station_id in self.grid.get((row + d_row, col + d_col), ()):
                    node = self.nodes[station_id]
                    if manhattan_distance_m(lat, lon, node["lat"], node["lon"]) <= radius_meters:
                        found.append(station_id)
        return found

    def nearest(self, lat: float, lon: float, kind: Optional[str] = None) -> tuple[dict, float]:
        """(station, walk_minutes) for the closest station, searching outward.

        Falls back to a full scan rather than returning nothing: somewhere in
        the far south-west of the bounding box the nearest station really is
        several kilometres away, and the answer is still that station.
        """
        candidates: Iterable[str] = ()
        for radius in (1000.0, 3000.0, 9000.0):
            candidates = [
                station_id
                for station_id in self.nearby(lat, lon, radius)
                if kind is None or self.nodes[station_id]["type"] == kind
            ]
            if candidates:
                break
        if not candidates:
            candidates = [sid for sid, n in self.nodes.items() if kind is None or n["type"] == kind]
        best_id = min(
            candidates,
            key=lambda sid: manhattan_distance_m(lat, lon, self.nodes[sid]["lat"], self.nodes[sid]["lon"]),
        )
        node = self.nodes[best_id]
        meters = manhattan_distance_m(lat, lon, node["lat"], node["lon"])
        return node, meters / constants.WALK_SPEED_MPM

    # -- costs -------------------------------------------------------------

    def wait_mins(self, station_id: str, line: str) -> float:
        if self.nodes[station_id]["type"] == "brt":
            return constants.BRT_WAIT_MINS
        return constants.METRO_WAIT_MINS_BY_LINE.get(str(line), constants.METRO_WAIT_MINS_DEFAULT)

    def ride_mins(self, station_id: str) -> float:
        if self.nodes[station_id]["type"] == "brt":
            return constants.BRT_RIDE_MINS_PER_STATION
        return constants.METRO_RIDE_MINS_PER_STATION

    def lines(self, station_id: str) -> tuple[str, ...]:
        # A node with no line recorded still has to be routable, so it gets one
        # anonymous line of its own: it can be ridden along its relations and
        # transferred out of, it just cannot share a line with anything else.
        recorded = self.nodes[station_id].get("lines") or ()
        return tuple(str(line) for line in recorded) or (f"_{station_id}",)


def _build_network() -> _Network:
    from app.spatial.transit import TRANSIT_NODES

    return _Network(TRANSIT_NODES)


NETWORK = _build_network()


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def _arrival_times(lat: float, lon: float) -> dict[str, float]:
    """Minutes from (lat, lon) to every station reachable by public transport.

    One Dijkstra over the (station, line) state graph. The returned figure
    includes the walk to the boarding station and every wait along the way,
    so it is a door-to-platform time, not a platform-to-platform one.
    """
    network = NETWORK
    heap: list[tuple[float, str, str]] = []
    best: dict[tuple[str, str], float] = {}

    # Boarding: walk to any station within reach, then wait for a line there.
    access = network.nearby(lat, lon, MAX_ACCESS_WALK_METERS)
    if not access:
        access = [network.nearest(lat, lon)[0]["id"]]
    for station_id in access:
        node = network.nodes[station_id]
        walk = manhattan_distance_m(lat, lon, node["lat"], node["lon"]) / constants.WALK_SPEED_MPM
        for line in network.lines(station_id):
            cost = walk + network.wait_mins(station_id, line)
            if cost < best.get((station_id, line), math.inf):
                best[(station_id, line)] = cost
                heapq.heappush(heap, (cost, station_id, line))

    while heap:
        cost, station_id, line = heapq.heappop(heap)
        if cost > best.get((station_id, line), math.inf):
            continue

        def relax(next_station: str, next_line: str, added: float) -> None:
            total = cost + added
            if total < best.get((next_station, next_line), math.inf):
                best[(next_station, next_line)] = total
                heapq.heappush(heap, (total, next_station, next_line))

        node = network.nodes[station_id]
        # Stay on the line: ride to the adjacent stations that share it.
        for neighbour_id in node.get("relations", ()):
            neighbour = network.nodes.get(neighbour_id)
            if neighbour is None:
                continue
            if line in network.lines(neighbour_id) or not (node.get("lines") and neighbour.get("lines")):
                relax(neighbour_id, line, network.ride_mins(station_id))

        # Change line without leaving the station (an interchange), then wait.
        for other_line in network.lines(station_id):
            if other_line == line:
                continue
            passage = constants.METRO_LINE_CHANGE_MINS if node["type"] == "metro" else 0.0
            relax(station_id, other_line, passage + network.wait_mins(station_id, other_line))

        # Change by walking to a different station -- metro to BRT, or one BRT
        # corridor to another -- then wait there.
        for other_id, walk_mins in network.walk_transfers.get(station_id, ()):
            for other_line in network.lines(other_id):
                relax(other_id, other_line, walk_mins + network.wait_mins(other_id, other_line))

    arrivals: dict[str, float] = {}
    for (station_id, _line), cost in best.items():
        if cost < arrivals.get(station_id, math.inf):
            arrivals[station_id] = cost
    return arrivals


@lru_cache(maxsize=64)
def _arrival_times_cached(lat_key: int, lon_key: int) -> dict[str, float]:
    return _arrival_times(lat_key / 10_000.0, lon_key / 10_000.0)


def arrival_times(lat: float, lon: float) -> dict[str, float]:
    """`_arrival_times`, memoised on the point rounded to ~11 metres.

    A search scores thousands of listings against one workplace; rounding lets
    every one of them share a single traversal, and 11 metres is far inside
    the model's own accuracy."""
    return _arrival_times_cached(round(lat * 10_000), round(lon * 10_000))


def transit_travel_minutes(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
) -> float:
    """Door-to-door public-transport time in minutes.

    The trip is charged from the destination side: the network is traversed
    once from (dest_lat, dest_lon) and each station near the origin is then
    offered as an alighting point, the total being the arrival time at that
    station plus the walk from it. Walking the whole way is always in the
    running, which is what makes a short trip come out as a short trip
    instead of accumulating a wait it would never incur.
    """
    direct_walk = manhattan_distance_m(origin_lat, origin_lon, dest_lat, dest_lon) / constants.WALK_SPEED_MPM
    arrivals = arrival_times(dest_lat, dest_lon)
    if not arrivals:
        return direct_walk

    network = NETWORK
    egress = network.nearby(origin_lat, origin_lon, MAX_ACCESS_WALK_METERS)
    if not egress:
        egress = [network.nearest(origin_lat, origin_lon)[0]["id"]]

    best = direct_walk
    for station_id in egress:
        arrival = arrivals.get(station_id)
        if arrival is None:
            continue
        node = network.nodes[station_id]
        walk = manhattan_distance_m(origin_lat, origin_lon, node["lat"], node["lon"]) / constants.WALK_SPEED_MPM
        total = arrival + walk
        if total < best:
            best = total
    return best


def nearest_metro_walk_minutes(lat: float, lon: float) -> tuple[dict, float, float]:
    """(station, distance_meters, walk_minutes) for the closest metro station.

    Distance is Manhattan, not straight-line: the number feeds a "how long to
    walk there" score, and the walk follows the street grid.
    """
    node, walk_mins = NETWORK.nearest(lat, lon, kind="metro")
    return node, walk_mins * constants.WALK_SPEED_MPM, walk_mins
