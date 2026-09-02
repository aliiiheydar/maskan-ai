"""app.spatial.isochrone -- the reachability shape drawn on the map.

The point of these is the *contract* the map relies on, not the exact
geometry: one shape rather than a heap of circles, sized by the same speed
constants the ranking scores commutes with, and never smaller for a mode that
can only add to walking.
"""

import math

import pytest
from shapely.geometry import Point

from app.core import constants
from app.spatial.isochrone import compute_isochrone_geometry

# Valiasr / Vanak, well inside the transit network.
LAT, LON = 35.7575, 51.4100


def _radius_km(geometry, lat: float, lon: float) -> float:
    """Roughly how far the shape reaches from a point, in kilometres."""
    minx, miny, maxx, maxy = geometry.bounds
    lon_km = 111.32 * math.cos(math.radians(lat))
    return max((maxx - lon) * lon_km, (lon - minx) * lon_km, (maxy - lat) * 111.32, (lat - miny) * 111.32)


def test_no_time_reaches_nowhere():
    assert compute_isochrone_geometry(LAT, LON, 0.0, "transit") is None
    assert compute_isochrone_geometry(LAT, LON, -5.0, "walk") is None


def test_an_unknown_mode_is_an_error_rather_than_an_empty_map():
    with pytest.raises(ValueError, match="Unknown commute mode"):
        compute_isochrone_geometry(LAT, LON, 20.0, "teleport")


def test_walk_reaches_the_distance_the_walk_speed_buys():
    geometry = compute_isochrone_geometry(LAT, LON, 30.0, "walk")
    expected_km = 30.0 * constants.WALK_SPEED_MPM / 1000.0
    # Loose: the buffer is a polygon approximation of a circle, and simplify
    # pulls its vertices in a little.
    assert _radius_km(geometry, LAT, LON) == pytest.approx(expected_km, rel=0.05)


def test_drive_reaches_further_than_walk_in_the_same_time():
    minutes = 20.0
    walk = compute_isochrone_geometry(LAT, LON, minutes, "walk")
    drive = compute_isochrone_geometry(LAT, LON, minutes, "drive")
    assert _radius_km(drive, LAT, LON) > _radius_km(walk, LAT, LON)


def test_the_shape_contains_the_point_it_was_drawn_from():
    for mode in ("walk", "drive", "transit"):
        assert compute_isochrone_geometry(LAT, LON, 25.0, mode).contains(Point(LON, LAT)), mode


def test_transit_never_loses_ground_that_walking_already_covered():
    """Direct walking is unioned in, so riding can only add. A transit shape
    that excluded the doorstep would be telling the user they cannot reach
    where they are standing."""
    minutes = 25.0
    walk = compute_isochrone_geometry(LAT, LON, minutes, "walk")
    transit = compute_isochrone_geometry(LAT, LON, minutes, "transit")
    assert transit.area >= walk.area
    # Not `contains`: the two shapes are simplified independently, so their
    # shared edge can disagree by up to the 25 m tolerance in either
    # direction. A sliver of that width is the approximation, not a hole.
    assert walk.difference(transit).area / walk.area < 0.01


def test_a_longer_budget_reaches_at_least_as_far():
    near = compute_isochrone_geometry(LAT, LON, 15.0, "transit")
    far = compute_isochrone_geometry(LAT, LON, 45.0, "transit")
    assert far.area > near.area


def test_the_answer_is_one_merged_shape_not_a_pile_of_circles():
    """The reason this module exists: ~130 stacked station circles flooded the
    map. Whatever comes back must be a single (multi)polygon, and a modest one
    -- simplify is what keeps the payload and the render cheap."""
    geometry = compute_isochrone_geometry(LAT, LON, 40.0, "transit")
    assert geometry.geom_type in {"Polygon", "MultiPolygon"}
    assert geometry.is_valid
    assert len(geometry.__geo_interface__["coordinates"]) < 130
