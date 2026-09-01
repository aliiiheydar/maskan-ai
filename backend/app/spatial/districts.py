"""Tehran's 22 official municipal districts (منطقه ۱ تا ۲۲), sourced as a
GeoJSON polygon FeatureCollection. Used to enrich listings with their real
administrative district, alongside (not instead of) the informal neighborhood
name already assigned from NEIGHBORHOOD_ANCHORS -- Tehran real estate
listings conventionally show both, e.g. "یوسف‌آباد، منطقه ۶".
"""

import json
from typing import Optional

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from app.core import paths

_DISTRICTS_PATH = paths.asset("districts.json")


def _load_districts() -> list[tuple[str, BaseGeometry]]:
    geojson = json.loads(_DISTRICTS_PATH.read_text(encoding="utf-8"))
    districts: list[tuple[str, BaseGeometry]] = []
    for feature in geojson.get("features", []):
        name = feature.get("properties", {}).get("name")
        if name:
            districts.append((name, shape(feature["geometry"])))
    return districts


_DISTRICTS = _load_districts()


def find_district(lat: float, lon: float) -> Optional[str]:
    """Return the official district name (e.g. "منطقه 6") containing the
    point, or None if it falls outside all mapped districts."""
    point = Point(lon, lat)
    for name, polygon in _DISTRICTS:
        if polygon.contains(point):
            return name
    return None
