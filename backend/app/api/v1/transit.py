"""GET /api/v1/transit/stations -- Tehran Metro & BRT station coordinates."""

from fastapi import APIRouter

from app.api.v1.schemas import TransitStation
from app.spatial.transit import TRANSIT_NODES

router = APIRouter()


@router.get("/transit/stations", response_model=list[TransitStation])
async def get_transit_stations() -> list[dict]:
    return TRANSIT_NODES
