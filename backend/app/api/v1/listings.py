"""GET /api/v1/listings/{id} -- single listing detail view."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_repository
from app.core.models import Listing
from app.data.repository import ListingRepository

router = APIRouter()


@router.get("/listings/{listing_id}", response_model=Listing)
async def get_listing(listing_id: str, repository: ListingRepository = Depends(get_repository)) -> Listing:
    listing = repository.get(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id!r} not found.")
    return listing
