"""GET /api/v1/geo/* -- the shapes the map draws search areas from.

GET /geo/neighborhoods         -- all 370 محله, without polygons
GET /geo/neighborhoods/shapes  -- polygons for the selected keys only
GET /geo/neighborhoods/area    -- the selected keys dissolved into one outline
GET /geo/neighborhood-at       -- which محله a map coordinate falls in
GET /geo/city                  -- Tehran's municipal boundary
"""

import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from shapely.geometry import mapping
from shapely.ops import transform, unary_union

from app.api.v1.schemas import CityBoundary, NeighborhoodShape, NeighborhoodSummary, SearchArea
from app.spatial import neighborhoods
from app.spatial.city import CITY_BOUNDARY, CITY_NAME

router = APIRouter()

# Requesting every polygon at once would be ~700 KB of GeoJSON; the map only
# ever outlines the current selection, which is a handful.
_MAX_SHAPES_PER_REQUEST = 60

# Neighborhood polygons that meet on the ground rarely share their vertices in
# the source data: of the ~1,000 neighbouring pairs in the corpus the median
# pair is 4 metres apart and the 90th percentile 30 metres, which is a street
# width, not a gap anyone would call a distance. Drawn as-is those slivers read
# as internal borders inside a single selected area -- exactly what the
# dissolve exists to remove. Growing every polygon by this much closes them;
# shrinking the union back by the same amount restores the outer edge.
#
# 25 m closes about 93% of adjacent pairs. Beyond that the buffer starts
# swallowing genuinely separate blocks, so a pair further apart than this stays
# two shapes.
_SEAM_TOLERANCE_M = 25.0

# Buffering in raw degrees would grow a shape further north-south than
# east-west (a degree of longitude is ~0.81 of a degree of latitude at
# Tehran's 35.7 deg), so the closing distance is applied in a local
# equirectangular projection instead, where a unit really is a metre.
_LAT0, _LON0 = 35.70, 51.35
_M_PER_DEG = 111_320.0
_LON_SCALE = math.cos(math.radians(_LAT0))


def _to_metres(lon: float, lat: float) -> tuple[float, float]:
    return ((lon - _LON0) * _M_PER_DEG * _LON_SCALE, (lat - _LAT0) * _M_PER_DEG)


def _to_degrees(x: float, y: float) -> tuple[float, float]:
    return (_LON0 + x / (_M_PER_DEG * _LON_SCALE), _LAT0 + y / _M_PER_DEG)


def _dissolve(polygons: list) -> object:
    """The selected shapes as one outline, with near-touching edges joined.

    A close-and-open round trip in metres: every polygon grows by the seam
    tolerance, the union is taken, and the result shrinks back. Whatever was
    within the tolerance of its neighbour is now one shape with no line
    through it; whatever was further stays separate.
    """
    projected = [transform(_to_metres, polygon) for polygon in polygons]
    closed = unary_union([polygon.buffer(_SEAM_TOLERANCE_M) for polygon in projected])
    opened = closed.buffer(-_SEAM_TOLERANCE_M)
    if opened.is_empty:
        opened = unary_union(projected)
    return transform(_to_degrees, opened)


def _summary(n: neighborhoods.Neighborhood) -> NeighborhoodSummary:
    return NeighborhoodSummary(
        key=n.key,
        title=n.title,
        subtitle=n.subtitle,
        center_lat=n.center_lat,
        center_lon=n.center_lon,
        min_lat=n.min_lat,
        min_lon=n.min_lon,
        max_lat=n.max_lat,
        max_lon=n.max_lon,
        area_sqkm=round(neighborhoods.area_sqkm(n), 3),
    )


def _requested_keys(keys: str) -> list[str]:
    requested = [key.strip() for key in keys.split(",") if key.strip()]
    if len(requested) > _MAX_SHAPES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_MAX_SHAPES_PER_REQUEST} neighborhood shapes may be requested at once.",
        )
    return requested


@router.get("/geo/neighborhoods", response_model=list[NeighborhoodSummary])
async def list_neighborhoods() -> list[NeighborhoodSummary]:
    return [_summary(n) for n in neighborhoods.NEIGHBORHOODS]


@router.get("/geo/neighborhoods/shapes", response_model=list[NeighborhoodShape])
async def get_neighborhood_shapes(
    keys: str = Query(..., description="Comma-separated neighborhood keys"),
) -> list[NeighborhoodShape]:
    requested = _requested_keys(keys)
    if not requested:
        return []

    return [
        NeighborhoodShape(key=n.key, title=n.title, geometry=mapping(n.polygon))
        for n in neighborhoods.polygons_for(neighborhoods.normalize_keys(requested))
    ]


@router.get("/geo/neighborhoods/area", response_model=SearchArea)
async def get_search_area(
    keys: str = Query(..., description="Comma-separated neighborhood keys"),
) -> SearchArea:
    """The chosen neighborhoods as one shape, with the borders between
    adjacent choices dissolved away."""
    requested = _requested_keys(keys)
    resolved = neighborhoods.normalize_keys(requested) if requested else []
    polygons = [n.polygon for n in neighborhoods.polygons_for(resolved)]
    if not polygons:
        return SearchArea(keys=[], geometry=None)

    return SearchArea(keys=resolved, geometry=mapping(_dissolve(polygons)))


@router.get("/geo/neighborhood-at", response_model=Optional[NeighborhoodSummary])
async def get_neighborhood_at(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> Optional[NeighborhoodSummary]:
    """Which محله a point on the map falls in.

    The polygons cover about two thirds of the city, so a click on a park, a
    highway or an unmapped pocket legitimately answers "none" -- the caller
    shows that as "this point is not inside a known محله" rather than as an
    error.
    """
    found = neighborhoods.find_neighborhood(lat, lon)
    return _summary(found) if found else None


@router.get("/geo/city", response_model=CityBoundary)
async def get_city_boundary() -> CityBoundary:
    return CityBoundary(name=CITY_NAME, geometry=mapping(CITY_BOUNDARY))
