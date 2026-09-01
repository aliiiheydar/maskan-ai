import pytest

from app.core.constants import TARH_TERAFIK_BBOX
from app.spatial.distance import haversine_distance_km, manhattan_distance_m
from app.spatial.transit import estimate_commute_time, find_nearest_metro_station, is_inside_tarh_terafik


def test_haversine_known_distance():
    # Tajrish to Imam Khomeini Sq metro interchange, ~13 km apart.
    dist = haversine_distance_km(35.8044, 51.4300, 35.6892, 51.4173)
    assert dist == pytest.approx(13.0, rel=0.1)


def test_haversine_zero_distance_for_same_point():
    assert haversine_distance_km(35.7, 51.4, 35.7, 51.4) == pytest.approx(0.0, abs=1e-9)


def test_find_nearest_metro_station_returns_metro_type_and_correct_walk_time():
    station, dist_km, walk_mins = find_nearest_metro_station(35.80464927254761, 51.43348783883829)
    assert station["type"] == "metro"
    assert station["id"] == "metro-tajrish"  # Tajrish, exact match
    assert dist_km == pytest.approx(0.0, abs=1e-6)
    assert walk_mins == pytest.approx(dist_km * 1000 / 80.0)


def test_is_inside_tarh_terafik_true_inside_zone():
    lat = (TARH_TERAFIK_BBOX.min_lat + TARH_TERAFIK_BBOX.max_lat) / 2
    lon = (TARH_TERAFIK_BBOX.min_lon + TARH_TERAFIK_BBOX.max_lon) / 2
    assert is_inside_tarh_terafik(lat, lon) is True


def test_is_inside_tarh_terafik_false_outside_zone():
    # Tehranpars, well east of the congestion zone.
    assert is_inside_tarh_terafik(35.7350, 51.5100) is False


def test_estimate_commute_time_walk_mode():
    # Walking follows the street grid, so the distance is Manhattan, not the
    # straight line -- see app/spatial/distance.py.
    minutes = estimate_commute_time(35.70, 51.40, 35.70, 51.401, mode="walk")
    meters = manhattan_distance_m(35.70, 51.40, 35.70, 51.401)
    assert minutes == pytest.approx(meters / 80.0)


def test_estimate_commute_time_transit_mode_is_routed_not_averaged():
    origin = (35.70, 51.40)
    dest = (35.75, 51.42)
    minutes = estimate_commute_time(*origin, *dest, mode="transit")

    # A real route: walk, wait, ride, maybe change, walk. It has to cost more
    # than the ride alone and less than walking the whole way.
    walk_all_the_way = manhattan_distance_m(*origin, *dest) / 80.0
    assert 5.0 < minutes < walk_all_the_way


def test_estimate_commute_time_drive_mode_applies_congestion_penalty():
    lat = (TARH_TERAFIK_BBOX.min_lat + TARH_TERAFIK_BBOX.max_lat) / 2
    lon = (TARH_TERAFIK_BBOX.min_lon + TARH_TERAFIK_BBOX.max_lon) / 2
    dest_lat, dest_lon = lat + 0.02, lon + 0.02

    minutes = estimate_commute_time(lat, lon, dest_lat, dest_lon, mode="drive")
    dist_km = haversine_distance_km(lat, lon, dest_lat, dest_lon)
    expected = dist_km / 22.0 * 60.0 * 1.4
    assert minutes == pytest.approx(expected)


def test_estimate_commute_time_drive_mode_no_penalty_outside_zone():
    origin = (35.63, 51.34)  # Basij area, outside congestion zone
    dest = (35.64, 51.35)
    minutes = estimate_commute_time(*origin, *dest, mode="drive")
    dist_km = haversine_distance_km(*origin, *dest)
    assert minutes == pytest.approx(dist_km / 22.0 * 60.0)


def test_estimate_commute_time_invalid_mode_raises():
    with pytest.raises(ValueError):
        estimate_commute_time(35.70, 51.40, 35.71, 51.41, mode="teleport")
