"""In-memory listing repository (MVP stand-in for the PostgreSQL + PostGIS
store described in docs/ARCHITECTURE.md's Data Repository Layer)."""

from typing import Iterable, Optional

from app.core.models import Listing


class ListingRepository:
    def __init__(self) -> None:
        self._listings: dict[str, Listing] = {}

    def seed(self, listings: Iterable[Listing]) -> None:
        self._listings = {listing.id: listing for listing in listings}

    def all(self) -> list[Listing]:
        return list(self._listings.values())

    def get(self, listing_id: str) -> Optional[Listing]:
        return self._listings.get(listing_id)

    def __len__(self) -> int:
        return len(self._listings)
