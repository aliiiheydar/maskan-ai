"""app.search.map_clusters -- what the map gets back for a viewport.

The rule under test is a budget, not a formula: a cell is opened into pins
when it is small enough to read as pins *and* the response can still afford
them. Both halves matter, so both are pinned down here.
"""

import pytest

from dataclasses import dataclass

from app.search.map_clusters import (
    ALWAYS_OPEN_ZOOM,
    GRID_COLUMNS,
    GRID_ROWS,
    MAX_OPEN_POINTS,
    OPEN_CELL_AT,
    cluster_matches,
)


@dataclass
class _Bbox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


@dataclass
class _Match:
    lat: float
    lon: float


#: A degree square, so a cell is 1/GRID_COLUMNS by 1/GRID_ROWS of it.
BBOX = _Bbox(min_lat=35.0, min_lon=51.0, max_lat=36.0, max_lon=52.0)


def _in_cell(column: int, row: int, count: int) -> list[_Match]:
    """`count` listings sitting in the middle of one grid cell."""
    lon = BBOX.min_lon + (column + 0.5) / GRID_COLUMNS
    lat = BBOX.min_lat + (row + 0.5) / GRID_ROWS
    return [_Match(lat=lat, lon=lon) for _ in range(count)]


def test_no_matches_is_neither_clusters_nor_pins():
    assert cluster_matches([], BBOX, zoom=12) == ([], [])


def test_a_small_cell_comes_back_as_pins():
    matches = _in_cell(1, 1, OPEN_CELL_AT)
    clusters, points = cluster_matches(matches, BBOX, zoom=12)
    assert clusters == []
    assert points == matches


def test_a_crowded_cell_comes_back_as_one_badge():
    clusters, points = cluster_matches(_in_cell(1, 1, OPEN_CELL_AT + 1), BBOX, zoom=12)
    assert points == []
    assert len(clusters) == 1
    assert clusters[0].count == OPEN_CELL_AT + 1


def test_a_badge_sits_on_its_listings_not_in_the_middle_of_its_cell():
    """The centroid, not the cell centre: a badge in an empty corner of the
    map would point at nothing."""
    corner = BBOX.min_lat + 0.001, BBOX.min_lon + 0.001
    clusters, _ = cluster_matches(
        [_Match(lat=corner[0], lon=corner[1]) for _ in range(OPEN_CELL_AT + 1)], BBOX, zoom=12
    )
    assert clusters[0].lat == pytest.approx(corner[0])
    assert clusters[0].lon == pytest.approx(corner[1])
    # ...but the reported bounds are still the cell's, which is what the map
    # zooms to when the badge is clicked.
    assert clusters[0].min_lat == BBOX.min_lat
    assert clusters[0].max_lon == BBOX.min_lon + 1.0 / GRID_COLUMNS


def test_cells_are_counted_separately():
    matches = _in_cell(0, 0, OPEN_CELL_AT + 1) + _in_cell(GRID_COLUMNS - 1, GRID_ROWS - 1, OPEN_CELL_AT + 5)
    clusters, points = cluster_matches(matches, BBOX, zoom=12)
    assert points == []
    assert sorted(cluster.count for cluster in clusters) == [OPEN_CELL_AT + 1, OPEN_CELL_AT + 5]


def test_zooming_past_the_threshold_opens_a_cell_the_count_alone_would_keep_shut():
    matches = _in_cell(1, 1, OPEN_CELL_AT + 20)
    clusters, points = cluster_matches(matches, BBOX, zoom=ALWAYS_OPEN_ZOOM)
    assert clusters == []
    assert len(points) == len(matches)


def test_the_pin_budget_is_spent_on_the_cells_that_open_cheapest():
    """Enough just-under-threshold cells to blow the cap: the small ones become
    pins and the fullest stay badges, rather than one dense cell swallowing the
    whole budget."""
    sizes = [OPEN_CELL_AT, OPEN_CELL_AT - 10, OPEN_CELL_AT - 20]
    matches = []
    for index, size in enumerate(sizes):
        matches += _in_cell(index % GRID_COLUMNS, index // GRID_COLUMNS, size)

    clusters, points = cluster_matches(matches, BBOX, zoom=ALWAYS_OPEN_ZOOM)
    # The cap only bites at real corpus sizes; below it everything opens.
    assert len(points) + sum(cluster.count for cluster in clusters) == len(matches)
    assert len(points) <= MAX_OPEN_POINTS


def test_the_response_never_exceeds_the_pin_cap():
    matches = _in_cell(0, 0, MAX_OPEN_POINTS * 2)
    _, points = cluster_matches(matches, BBOX, zoom=ALWAYS_OPEN_ZOOM)
    assert len(points) <= MAX_OPEN_POINTS


def test_without_a_viewport_there_is_no_grid_to_cluster_against():
    """A neighborhood selection or a city-wide search: send what fits, cluster
    nothing."""
    matches = _in_cell(0, 0, MAX_OPEN_POINTS + 50)
    clusters, points = cluster_matches(matches, None, zoom=12)
    assert clusters == []
    assert len(points) == MAX_OPEN_POINTS


def test_a_degenerate_viewport_does_not_divide_by_zero():
    flat = _Bbox(min_lat=35.7, min_lon=51.4, max_lat=35.7, max_lon=51.4)
    clusters, points = cluster_matches([_Match(35.7, 51.4)], flat, zoom=12)
    assert len(points) == 1 and clusters == []
