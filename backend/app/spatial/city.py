"""Tehran's municipal boundary (the thick outline the map draws around the
default search area).

Sourced from ``tehran.geojson`` -- OpenStreetMap relation 6663864, the
admin_level=7 boundary of شهر تهران. The file also carries the relation's
label node, which is skipped: only the polygon is of interest here.
"""

import json
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

_CITY_PATH = Path(__file__).resolve().parent.parent / "data" / "tehran.geojson"

CITY_NAME = "شهر تهران"


def _load_city_boundary() -> BaseGeometry:
    geojson = json.loads(_CITY_PATH.read_text(encoding="utf-8"))
    polygons = [
        shape(feature["geometry"])
        for feature in geojson.get("features", [])
        if feature.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")
    ]
    if not polygons:
        raise ValueError(f"No city polygon found in {_CITY_PATH}")
    boundary = max(polygons, key=lambda p: p.area)
    return boundary if boundary.is_valid else boundary.buffer(0)


CITY_BOUNDARY: BaseGeometry = _load_city_boundary()
