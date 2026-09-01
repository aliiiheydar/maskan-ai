"""The listing repository: SQLite for storage and narrowing, memory for ranking.

The split is deliberate. Deciding *which* listings a query is even about is a
set-membership problem the database is far better at than Python -- an R*Tree
answers "everything in this viewport" without looking at the rest of the city,
and the column indexes answer the boolean and range filters the same way.
Deciding how *good* each survivor is means running the multi-criteria utility
formula over embeddings, so the surviving rows are hydrated from an in-memory
cache rather than re-parsed per query.

The database is the source of truth; the cache is a materialised view of it
built once at startup. ``seed()`` remains for tests and for the synthetic
corpus, and leaves the repository purely in-memory.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

import h3

from app.core.models import ExtractedSearchIntent, Listing
from app.data import database
from app.search.scoring import MarketBaselines

H3_RESOLUTION = 8

# The R*Tree narrows, the real columns decide.
#
# SQLite's rtree stores coordinates as 32-bit floats and deliberately rounds
# each box *outward* so that it can never miss a match. That guarantee is
# one-directional: a hit from the index may be a hair outside the rectangle.
# Testing the index for overlap and then the exact REAL columns for containment
# is the documented pattern, and here it is what stops the map's pin count from
# drifting away from the number shown above the feed.
_RTREE_BBOX = (
    "g.max_lat >= ? AND g.min_lat <= ? AND g.max_lon >= ? AND g.min_lon <= ? "
    "AND l.lat BETWEEN ? AND ? AND l.lon BETWEEN ? AND ?"
)


class ListingRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._listings: dict[str, Listing] = {}
        self._by_h3: dict[str, list[str]] = defaultdict(list)
        self._connection = connection
        self.baselines = MarketBaselines()

    # -- loading -----------------------------------------------------------

    def seed(self, listings: Iterable[Listing]) -> None:
        """Load an in-memory corpus, bypassing the database entirely."""
        self._listings = {listing.id: listing for listing in listings}
        self._by_h3 = defaultdict(list)
        for listing in self._listings.values():
            self._by_h3[listing.h3_index].append(listing.id)
        # Neighborhood price medians are a property of the corpus, not of a
        # query, so they are computed once here rather than inside the ranking
        # loop ("architectural suggestion.md" SS7.2).
        self.baselines = MarketBaselines.from_listings(self._listings.values())

    def open(self, path: Path = database.DEFAULT_DB_PATH) -> int:
        """Attach to the database and materialise its rows. Returns the count."""
        self._connection = database.connect(path, read_only=True)
        self.seed(database.load_all(self._connection))
        return len(self._listings)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def is_database_backed(self) -> bool:
        return self._connection is not None

    # -- reads -------------------------------------------------------------

    def all(self) -> list[Listing]:
        return list(self._listings.values())

    def get(self, listing_id: str) -> Optional[Listing]:
        return self._listings.get(listing_id)

    def __len__(self) -> int:
        return len(self._listings)

    def _hydrate(self, ids: Sequence[str]) -> list[Listing]:
        return [self._listings[listing_id] for listing_id in ids if listing_id in self._listings]

    # -- narrowing ---------------------------------------------------------

    def query_bbox(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[Listing]:
        """Listings inside the viewport.

        With a database attached this is an R*Tree range scan, which touches
        only the leaves the rectangle overlaps. Without one it falls back to
        the precomputed H3 cover, where two properties matter and both were
        once wrong:

        * The cell cover must be a *superset* of the bbox. ``polygon_to_cells``
          keeps only cells whose centre falls inside the polygon, so a viewport
          smaller than one res-8 hexagon (~1 km across -- i.e. any zoom past
          about 15) covered no cells at all and the map went empty exactly
          where it had just shown a cluster. ``contain="overlap"`` keeps every
          cell the bbox touches.
        * The cover must then be narrowed back down. A res-8 cell spills up to
          ~500 m past the viewport edge, so cell membership alone returned
          listings that are not on screen -- the feed's count then disagreed
          with the pins the user could see.
        """
        if self._connection is not None:
            rows = self._connection.execute(
                f"SELECT l.id FROM listings_geo AS g JOIN listings AS l ON l.rowid = g.id WHERE {_RTREE_BBOX}",
                (min_lat, max_lat, min_lon, max_lon) * 2,
            ).fetchall()
            return self._hydrate([row["id"] for row in rows])

        boundary = [
            (min_lat, min_lon),
            (min_lat, max_lon),
            (max_lat, max_lon),
            (max_lat, min_lon),
        ]
        try:
            cells = h3.h3shape_to_cells_experimental(h3.LatLngPoly(boundary), H3_RESOLUTION, contain="overlap")
            candidates: Iterable[Listing] = [
                self._listings[listing_id] for cell in cells for listing_id in self._by_h3.get(cell, [])
            ]
        except Exception:
            # Degenerate bbox (zero area, antimeridian): fall back to a scan,
            # still exact-filtered below.
            candidates = self._listings.values()

        return [
            listing
            for listing in candidates
            if min_lat <= listing.lat <= max_lat and min_lon <= listing.lon <= max_lon
        ]

    def query(
        self,
        intent: ExtractedSearchIntent,
        *,
        bbox: Optional[tuple[float, float, float, float]] = None,
        min_rooms: Optional[int] = None,
    ) -> list[Listing]:
        """Candidates for a search, with every *exact* predicate pushed into SQL.

        Only predicates whose SQL form is identical to the Python one live
        here. The budget ceilings deliberately do not: they are evaluated on
        the tabdil-converted deposit/rent rather than the advertised columns,
        and the area band carries a tolerance -- both stay in
        ``hard_constraint_mask`` so there is exactly one definition of each.
        Pushing down the rest still removes the great majority of the corpus
        before a single utility score is computed.
        """
        if self._connection is None:
            listings = (
                self.query_bbox(bbox[0], bbox[1], bbox[2], bbox[3]) if bbox is not None else list(self._listings.values())
            )
            return [listing for listing in listings if _matches_in_memory(listing, intent, min_rooms)]

        where: list[str] = []
        params: list = []
        joins = ""

        if bbox is not None:
            joins = " JOIN listings_geo AS g ON g.id = l.rowid"
            where.append(_RTREE_BBOX)
            # (min_lat, max_lat, min_lon, max_lon), once for the index overlap
            # test and once for the exact containment test.
            params += [bbox[0], bbox[2], bbox[1], bbox[3]] * 2

        if intent.target_neighborhood_keys:
            # NULL keys survive: a listing whose polygon we could not resolve is
            # decided by point-in-polygon later rather than being dropped here.
            placeholders = ", ".join("?" * len(intent.target_neighborhood_keys))
            where.append(f"(l.neighborhood_key IS NULL OR l.neighborhood_key IN ({placeholders}))")
            params += list(intent.target_neighborhood_keys)

        if min_rooms is not None:
            where.append("l.rooms >= ?")
            params.append(min_rooms)
        # آسانسور is not narrowed here. Mirrors hard_constraint_mask: a
        # walk-up is scored down in proportion to its floor rather than
        # removed, so the candidate set has to still contain it.
        if intent.must_have_parking:
            where.append("l.has_parking = 1")
        if intent.must_have_storage:
            where.append("l.has_storage = 1")
        if intent.must_have_balcony:
            where.append("l.has_balcony = 1")
        if intent.must_have_images:
            where.append("l.image_count > 0")
        # The one predicate every search carries: a shared-home advert and a
        # whole-unit advert are never wanted together.
        where.append("l.is_shared_living = ?")
        params.append(1 if intent.living_kind == "shared" else 0)
        if intent.full_rahn_only:
            where.append("l.is_full_rahn = 1")
        if intent.convertible_only:
            where.append("l.can_convert = 1")
        if intent.min_floor is not None:
            where.append("l.floor >= ?")
            params.append(intent.min_floor)
        if intent.max_floor is not None:
            where.append("l.floor <= ?")
            params.append(intent.max_floor)
        if intent.min_build_year is not None:
            where.append("l.build_year IS NOT NULL AND l.build_year >= ?")
            params.append(intent.min_build_year)
        if intent.min_deposit is not None:
            where.append("l.deposit_toman >= ?")
            params.append(intent.min_deposit)
        if intent.min_rent is not None:
            where.append("l.rent_toman >= ?")
            params.append(intent.min_rent)

        sql = f"SELECT l.id FROM listings AS l{joins}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self._connection.execute(sql, params).fetchall()
        return self._hydrate([row["id"] for row in rows])

    def search_text(self, query: str, limit: int = 500) -> list[Listing]:
        """Full-text matches over the Persian title and description, best first.

        Unused by the ranking path today -- the FTS index is there so a keyword
        query does not have to become a scan of 6,000 descriptions once the
        corpus grows past what fits comfortably in memory.
        """
        if self._connection is None or not query.strip():
            return []
        rows = self._connection.execute(
            "SELECT l.id FROM listings_fts AS f JOIN listings AS l ON l.rowid = f.rowid "
            "WHERE listings_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return self._hydrate([row["id"] for row in rows])


def _matches_in_memory(listing: Listing, intent: ExtractedSearchIntent, min_rooms: Optional[int]) -> bool:
    """The SQL predicates above, for the in-memory corpus. Kept beside them so
    the two cannot drift apart unnoticed."""
    if intent.target_neighborhood_keys and listing.neighborhood_key is not None:
        if listing.neighborhood_key not in set(intent.target_neighborhood_keys):
            return False
    if min_rooms is not None and listing.rooms < min_rooms:
        return False
    if listing.is_shared_living != (intent.living_kind == "shared"):
        return False
    if intent.must_have_parking and not listing.has_parking:
        return False
    if intent.must_have_storage and not listing.has_storage:
        return False
    if intent.must_have_balcony and not listing.has_balcony:
        return False
    if intent.must_have_images and listing.image_count <= 0:
        return False
    if intent.full_rahn_only and not listing.is_full_rahn:
        return False
    if intent.convertible_only and not listing.can_convert:
        return False
    if intent.min_floor is not None and listing.floor < intent.min_floor:
        return False
    if intent.max_floor is not None and listing.floor > intent.max_floor:
        return False
    if intent.min_build_year is not None and (listing.build_year is None or listing.build_year < intent.min_build_year):
        return False
    if intent.min_deposit is not None and listing.deposit_toman < intent.min_deposit:
        return False
    if intent.min_rent is not None and listing.rent_toman < intent.min_rent:
        return False
    return True
