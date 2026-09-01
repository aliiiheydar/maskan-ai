"""Server-side clustering for map-explore.

Map-explore used to send every match as its own pin -- ten thousand of them
on a city-wide view -- and let leaflet.markercluster work out the grouping in
the browser. That is the wrong division of labour twice over: the payload is
proportional to the corpus rather than to what can be drawn, and the clustering
itself runs on the main thread on every pan.

So the grouping happens here, over the viewport the client actually asked
about. The map gets back roughly a dozen counted cells -- the same shape Divar
answers a viewport with -- and a cell only comes apart into individual pins
once it is small enough to be worth reading as pins. Zooming in shrinks the
viewport, which shrinks each cell's count, which opens the cells: the map
"opens up" as the user goes in without the client deciding anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# Divar answers a viewport with about ten badges; more than that and the map
# is a wall of numbers rather than a read of where the listings are. 4x3 is
# that count at the aspect ratio of a landscape map panel.
GRID_COLUMNS = 4
GRID_ROWS = 3

# A cell holding no more than this is sent as individual pins: at this size
# the pins are distinguishable, and a badge would be hiding a handful of
# properties the user could simply see.
OPEN_CELL_AT = 30

# Past this zoom the user has asked for the properties themselves, so cells
# open regardless of their count -- subject to the payload cap below.
ALWAYS_OPEN_ZOOM = 16

# Ceiling on pins in one response. Reached only when many cells are just under
# OPEN_CELL_AT; the fullest cells stay clustered rather than the response
# growing without bound.
MAX_OPEN_POINTS = 400


@dataclass
class Cluster:
    lat: float
    lon: float
    count: int
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


@dataclass
class _Cell:
    members: list
    lat_sum: float = 0.0
    lon_sum: float = 0.0


def cluster_matches(
    matches: list,
    bbox,
    zoom: Optional[float],
) -> tuple[list[Cluster], list]:
    """Split `matches` into counted cells and the ones drawn as pins.

    `matches` is any sequence of objects carrying `.lat`/`.lon`; the ones that
    land in an opened cell are returned as-is, in the caller's own type.
    """
    if not matches:
        return [], []
    if bbox is None:
        # No viewport to grid against (the whole city, or a neighborhood
        # selection): send what fits and count the rest as one cell.
        return [], list(matches)[:MAX_OPEN_POINTS]

    lat_span = max(bbox.max_lat - bbox.min_lat, 1e-9)
    lon_span = max(bbox.max_lon - bbox.min_lon, 1e-9)

    cells: dict[tuple[int, int], _Cell] = {}
    for match in matches:
        # Clamped rather than dropped: a listing exactly on the edge belongs to
        # the edge cell, and the prefilter has already limited these to the box.
        column = min(GRID_COLUMNS - 1, max(0, int((match.lon - bbox.min_lon) / lon_span * GRID_COLUMNS)))
        row = min(GRID_ROWS - 1, max(0, int((match.lat - bbox.min_lat) / lat_span * GRID_ROWS)))
        cell = cells.setdefault((column, row), _Cell(members=[]))
        cell.members.append(match)
        cell.lat_sum += match.lat
        cell.lon_sum += match.lon

    # Smallest first, so the pin budget is spent on the cells that open most
    # cheaply instead of on one dense cell that swallows all of it.
    ordered = sorted(cells.items(), key=lambda item: len(item[1].members))
    open_at = float("inf") if (zoom is not None and zoom >= ALWAYS_OPEN_ZOOM) else OPEN_CELL_AT

    clusters: list[Cluster] = []
    points: list = []
    for (column, row), cell in ordered:
        count = len(cell.members)
        if count <= open_at and len(points) + count <= MAX_OPEN_POINTS:
            points.extend(cell.members)
            continue
        clusters.append(
            Cluster(
                # The centroid of the listings, not of the cell: a badge should
                # sit where the properties are, not in the middle of an empty
                # square whose corner happens to hold them all.
                lat=cell.lat_sum / count,
                lon=cell.lon_sum / count,
                count=count,
                min_lat=bbox.min_lat + row * lat_span / GRID_ROWS,
                min_lon=bbox.min_lon + column * lon_span / GRID_COLUMNS,
                max_lat=bbox.min_lat + (row + 1) * lat_span / GRID_ROWS,
                max_lon=bbox.min_lon + (column + 1) * lon_span / GRID_COLUMNS,
            )
        )
    return clusters, points
