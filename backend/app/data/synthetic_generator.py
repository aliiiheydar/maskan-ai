"""Synthetic listing generation. Deferred to a later data-generation phase --
see docs/DATA_SCHEMA.md section 3 for the neighborhood distribution rules."""

from app.core.schemas import Listing


def generate_synthetic_listings(n: int = 1000) -> list[Listing]:
    raise NotImplementedError
