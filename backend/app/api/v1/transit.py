"""GET /api/v1/transit/stations -- Tehran Metro & BRT station coordinates.
GET /api/v1/transit/isochrone -- commute-time reachability geometry.
GET /api/v1/transit/congestion-zones -- Tarh-e Terafik / Aloodegi boundaries.
"""

from typing import Literal

from fastapi import APIRouter, Query
from shapely.geometry import mapping

from app.api.v1.schemas import CongestionZone, IsochroneResponse, TransitStation
from app.spatial.isochrone import compute_isochrone_geometry
from app.spatial.transit import TRANSIT_NODES, get_congestion_zones

router = APIRouter()


@router.get("/transit/stations", response_model=list[TransitStation])
async def get_transit_stations() -> list[dict]:
    return TRANSIT_NODES


@router.get("/transit/congestion-zones", response_model=list[CongestionZone])
async def get_transit_congestion_zones() -> list[CongestionZone]:
    return [
        CongestionZone(zone=zone, label=label, geometry=mapping(polygon))
        for zone, label, polygon in get_congestion_zones()
    ]


@router.get("/transit/isochrone", response_model=IsochroneResponse)
async def get_isochrone(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    max_minutes: float = Query(..., gt=0, le=180),
    mode: Literal["walk", "transit", "drive"] = "transit",
) -> IsochroneResponse:
    geometry = compute_isochrone_geometry(lat, lon, max_minutes, mode)
    return IsochroneResponse(mode=mode, geometry=mapping(geometry) if geometry is not None else None)
