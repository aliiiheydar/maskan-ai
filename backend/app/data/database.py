"""SQLite storage for the listing corpus.

Shape of the store, and why:

* **``listings``** holds one row per property. Every field the search engine
  filters on gets its own typed, indexed column; the complete ``Listing`` is
  *also* stored as JSON in ``payload``. That duplication is deliberate -- the
  columns exist so the database can narrow candidates without deserialising
  anything, and the document exists so hydration is one ``json.loads`` and a
  new optional field on the model needs no migration.
* **``listings_geo``** is an R*Tree. Map-explore's whole workload is "give me
  everything in this rectangle", which a B-tree on ``lat`` cannot answer
  without scanning half the city; an R*Tree answers it in log time on both
  axes at once. This is the single biggest latency lever in the app.
* **``listings_fts``** is an FTS5 index over the Persian title and description,
  stored pre-normalised (Arabic ی/ک folded, Persian digits converted) so that a
  query typed either way matches. It is an *external content* table: the text
  lives in ``listings`` and FTS5 only indexes it.
* **``embeddings``** keeps description vectors as raw float32 blobs in their
  own table, so the common query path never pages 6 KB of vector per row off
  disk to answer a filter.

Every row also carries a ``fingerprint``: a hash of the fields that identify a
*property* rather than an *advert*. Divar reposts the same flat under a fresh
token when an ad expires, so token identity alone lets the same home appear
three times in one result page. ``upsert`` uses the fingerprint to keep exactly
one row per property while still updating a row whose own token comes round
again.

Connections are opened in WAL mode with a large page cache and memory-mapped
reads: the corpus is read-almost-only, and WAL means a rebuild in one process
does not block queries in another.
"""

from __future__ import annotations

import array
import hashlib
import json
import lzma
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Optional

from app.core import paths
from app.core.config import settings
from app.core.models import Listing
from app.core.shared_living import is_not_a_home, is_parking_rental
from app.core.normalizers import normalize_persian_text, parse_persian_numbers

#: Where the corpus is read from and written to. Inside the package by
#: default, which is what a checkout run from source wants; a container sets
#: DB_PATH to a mounted volume so the database outlives the image.
DEFAULT_DB_PATH = Path(settings.db_path) if settings.db_path else paths.asset("maskan.db")

#: The shipped corpus, compressed. See paths.SEED_DIR.
SEED_DB_PATH = paths.SEED_DIR / "maskan.db.xz"

# Columns that exist purely so SQLite can filter and sort without touching the
# JSON payload. Kept in one place because the schema, the INSERT and the
# row-building code all have to agree on the order.
_INDEXED_COLUMNS: tuple[str, ...] = (
    "id",
    "neighborhood_key",
    "district",
    "deposit_toman",
    "rent_toman",
    "effective_monthly_cost",
    "can_convert",
    "is_full_rahn",
    "is_shared_living",
    "area_sqm",
    "rooms",
    "floor",
    "total_floors",
    "has_elevator",
    "has_parking",
    "has_balcony",
    "has_storage",
    "build_year",
    "lat",
    "lon",
    "h3_index",
    "metro_walk_mins",
    "in_tarh_terafik",
    "in_tarh_aloodegi",
    "image_count",
    "is_furnished",
    "is_renovated",
    "pets_policy",
    "source",
    "fingerprint",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    rowid                  INTEGER PRIMARY KEY,
    id                     TEXT    NOT NULL UNIQUE,
    neighborhood_key       TEXT,
    district               TEXT,
    deposit_toman          INTEGER NOT NULL,
    rent_toman             INTEGER NOT NULL,
    effective_monthly_cost INTEGER NOT NULL,
    can_convert            INTEGER NOT NULL,
    is_full_rahn           INTEGER NOT NULL,
    is_shared_living       INTEGER NOT NULL DEFAULT 0,
    area_sqm               INTEGER NOT NULL,
    rooms                  INTEGER NOT NULL,
    floor                  INTEGER NOT NULL,
    total_floors           INTEGER NOT NULL,
    has_elevator           INTEGER NOT NULL,
    has_parking            INTEGER NOT NULL,
    has_balcony            INTEGER NOT NULL,
    has_storage            INTEGER NOT NULL,
    build_year             INTEGER,
    lat                    REAL    NOT NULL,
    lon                    REAL    NOT NULL,
    h3_index               TEXT    NOT NULL,
    metro_walk_mins        REAL    NOT NULL,
    in_tarh_terafik        INTEGER NOT NULL,
    in_tarh_aloodegi       INTEGER NOT NULL,
    image_count            INTEGER NOT NULL,
    is_furnished           INTEGER NOT NULL,
    is_renovated           INTEGER NOT NULL,
    pets_policy            TEXT,
    source                 TEXT    NOT NULL,
    -- Identity of the *property*, as opposed to the advert (see upsert).
    fingerprint            TEXT    NOT NULL,
    -- Search text, pre-normalised for FTS; the display strings live in payload.
    search_text            TEXT    NOT NULL,
    payload                TEXT    NOT NULL
);

-- The composite ones are ordered by what the UI actually narrows on first:
-- an area or neighborhood bound, then price. That keeps the common panel
-- search a range scan on one index rather than a scan of the table.
CREATE INDEX IF NOT EXISTS idx_listings_cost      ON listings(effective_monthly_cost);
-- Every search filters on this first (shared homes are a separate market),
-- so it leads the composite the ranked search then narrows on price with.
CREATE INDEX IF NOT EXISTS idx_listings_shared    ON listings(is_shared_living, effective_monthly_cost);
CREATE INDEX IF NOT EXISTS idx_listings_area_cost ON listings(area_sqm, effective_monthly_cost);
CREATE INDEX IF NOT EXISTS idx_listings_hood      ON listings(neighborhood_key, effective_monthly_cost);
CREATE INDEX IF NOT EXISTS idx_listings_rooms     ON listings(rooms, area_sqm);
CREATE INDEX IF NOT EXISTS idx_listings_h3        ON listings(h3_index);
CREATE INDEX IF NOT EXISTS idx_listings_deposit   ON listings(deposit_toman);
CREATE INDEX IF NOT EXISTS idx_listings_rent      ON listings(rent_toman);
CREATE INDEX IF NOT EXISTS idx_listings_metro     ON listings(metro_walk_mins);
CREATE INDEX IF NOT EXISTS idx_listings_finger    ON listings(fingerprint);

CREATE VIRTUAL TABLE IF NOT EXISTS listings_geo USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);

CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
    search_text,
    content='listings',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS embeddings (
    rowid     INTEGER PRIMARY KEY REFERENCES listings(rowid) ON DELETE CASCADE,
    dimension INTEGER NOT NULL,
    vector    BLOB    NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

#: meta key recording which revision of the parking rule a corpus was flagged
#: with. The rule is read off advertisers' spelling and keeps meeting new ways
#: to write "parking", so bump the revision whenever app.core.shared_living
#: learns one and every existing database re-runs the rule on its next write.
_PARKING_MIGRATION = "migration:parking_flagged"
_PARKING_RULE_REVISION = "2"


def _backfill(connection: sqlite3.Connection, predicate) -> int:
    """Flag every stored row `predicate` accepts, from its payload.

    Read back from the payload rather than from a re-crawl: the title and the
    description are already there, and they are exactly what the classifiers
    read, so the result is identical to what enrichment would have written --
    and a corpus that took hours to crawl does not have to be rebuilt to gain
    a flag.
    """
    flagged = [
        (row["rowid"],)
        for row in connection.execute("SELECT rowid, payload FROM listings WHERE is_shared_living = 0")
        if predicate(json.loads(row["payload"]))
    ]
    connection.executemany("UPDATE listings SET is_shared_living = 1 WHERE rowid = ?", flagged)
    return len(flagged)


def migrate(connection: sqlite3.Connection) -> int:
    """Bring an already-built database up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op on a table that exists, so a new
    column has to be added -- and filled -- explicitly.

    Two migrations so far, both feeding the one ``is_shared_living`` column:
    the column itself, and the later discovery that parking spaces are let
    under the same category as apartments (see app.core.shared_living). The
    second one has no schema change to detect it by, so it stamps ``meta``
    with the revision of the parking rule it ran -- re-flagging on every open
    would be harmless but would read all 21k payloads each time the corpus is
    written to, and a stale stamp is what tells a corpus flagged under an older
    rule to run the current one.

    Returns how many rows this call flagged.
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(listings)")}
    # No table yet (a fresh database): _SCHEMA creates it with the column
    # already in place, and enrichment flags every row on the way in.
    if not columns:
        return 0

    flagged = 0
    with connection:
        # The migration records itself here, so it has to exist before the
        # schema script runs (which is after this function -- see
        # upsert_listings).
        connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if "is_shared_living" not in columns:
            connection.execute("ALTER TABLE listings ADD COLUMN is_shared_living INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_shared ON listings(is_shared_living, effective_monthly_cost)"
            )
            flagged += _backfill(connection, lambda p: is_not_a_home(p.get("title"), p.get("description")))
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_PARKING_MIGRATION, _PARKING_RULE_REVISION),
            )
            return flagged

        stamp = connection.execute(
            "SELECT value FROM meta WHERE key = ?", (_PARKING_MIGRATION,)
        ).fetchone()
        if stamp is None or stamp["value"] != _PARKING_RULE_REVISION:
            flagged += _backfill(connection, lambda p: is_parking_rental(p.get("title")))
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_PARKING_MIGRATION, _PARKING_RULE_REVISION),
            )
    return flagged


def connect(path: Path = DEFAULT_DB_PATH, *, read_only: bool = False) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro" if read_only else f"file:{path}"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    if not read_only:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    # ~64 MB of page cache and 256 MB of mmap: the whole corpus and all its
    # indexes fit, so after the first query the store is effectively in RAM
    # while still being a real, durable database.
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("PRAGMA mmap_size=268435456")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _search_text(listing: Listing) -> str:
    parts = [listing.title, listing.description, listing.neighborhood, *listing.suitable_for]
    return normalize_persian_text(parse_persian_numbers(" \n".join(part for part in parts if part)))


def fingerprint(listing: Listing) -> str:
    """Identity of the property behind the advert.

    Built from the handful of fields a repost cannot change without becoming a
    different home: where it is, how big it is, and what it costs. The title is
    deliberately left out -- advertisers rewrite it between postings -- and so
    is the description, for the same reason.
    """
    parts = (
        listing.neighborhood_key or "",
        str(listing.area_sqm),
        str(listing.rooms),
        str(listing.floor),
        str(listing.deposit_toman),
        str(listing.rent_toman),
        f"{listing.lat:.5f}",
        f"{listing.lon:.5f}",
    )
    return hashlib.blake2b("|".join(parts).encode("utf-8"), digest_size=12).hexdigest()


def _row(listing: Listing) -> tuple:
    payload = listing.model_dump(exclude={"embedding"})
    values = {
        "id": listing.id,
        "neighborhood_key": listing.neighborhood_key,
        "district": listing.district,
        "deposit_toman": listing.deposit_toman,
        "rent_toman": listing.rent_toman,
        "effective_monthly_cost": listing.effective_monthly_cost,
        "can_convert": int(listing.can_convert),
        "is_full_rahn": int(listing.is_full_rahn),
        "is_shared_living": int(listing.is_shared_living),
        "area_sqm": listing.area_sqm,
        "rooms": listing.rooms,
        "floor": listing.floor,
        "total_floors": listing.total_floors,
        "has_elevator": int(listing.has_elevator),
        "has_parking": int(listing.has_parking),
        "has_balcony": int(listing.has_balcony),
        "has_storage": int(listing.has_storage),
        "build_year": listing.build_year,
        "lat": listing.lat,
        "lon": listing.lon,
        "h3_index": listing.h3_index,
        "metro_walk_mins": listing.metro_walk_mins,
        "in_tarh_terafik": int(listing.in_tarh_terafik),
        "in_tarh_aloodegi": int(listing.in_tarh_aloodegi),
        "image_count": listing.image_count,
        "is_furnished": int(listing.is_furnished),
        "is_renovated": int(listing.is_renovated),
        "pets_policy": listing.pets_policy,
        "source": listing.source,
        "fingerprint": fingerprint(listing),
    }
    return (
        *(values[column] for column in _INDEXED_COLUMNS),
        _search_text(listing),
        json.dumps(payload, ensure_ascii=False),
    )


def build(listings: Iterable[Listing], path: Path = DEFAULT_DB_PATH) -> int:
    """(Re)create the database from scratch and load it. Returns the row count.

    A rebuild drops and recreates rather than upserting: the corpus is a
    snapshot of a crawl, so "the new crawl replaces the old one" is the honest
    semantics and it keeps the R*Tree and the FTS index trivially consistent
    with the table.

    Reposts are collapsed here on the same fingerprint ``upsert`` uses, so a
    rebuild and a merge produce the same corpus. Without that, rebuilding would
    quietly reintroduce every duplicate an incremental run had removed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        connection.executescript(
            "DROP TABLE IF EXISTS listings_fts;"
            "DROP TABLE IF EXISTS listings_geo;"
            "DROP TABLE IF EXISTS embeddings;"
            "DROP TABLE IF EXISTS listings;"
        )
        connection.executescript(_SCHEMA)

        columns = ", ".join((*_INDEXED_COLUMNS, "search_text", "payload"))
        placeholders = ", ".join("?" * (len(_INDEXED_COLUMNS) + 2))
        seen: set[str] = set()
        rows = []
        for listing in listings:
            marker = fingerprint(listing)
            if marker in seen:
                continue
            seen.add(marker)
            rows.append(_row(listing))
        with connection:
            connection.executemany(f"INSERT INTO listings ({columns}) VALUES ({placeholders})", rows)
            # A point is a degenerate rectangle; the R*Tree stores it as one so
            # the same index answers both "in this box" and future radius work.
            connection.execute(
                "INSERT INTO listings_geo (id, min_lat, max_lat, min_lon, max_lon) "
                "SELECT rowid, lat, lat, lon, lon FROM listings"
            )
            connection.execute("INSERT INTO listings_fts (rowid, search_text) SELECT rowid, search_text FROM listings")
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('listing_count', ?)", (str(len(rows)),)
            )
        connection.execute("ANALYZE")
        return len(rows)
    finally:
        connection.close()


def upsert(listings: Iterable[Listing], path: Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Merge a fresh batch into an existing database, without a rebuild.

    This is the incremental counterpart to ``build``: the pipeline crawls a few
    hundred new adverts at a time, and re-deriving the entire corpus (and its
    R*Tree and FTS index) for each of those batches would be absurd.

    Three outcomes per incoming listing:

    * its token is already stored -- the row is **updated**, because the price
      or the photo set may have changed since we last saw it;
    * its fingerprint matches a *different* stored token -- it is a repost of a
      property we already hold, and is **skipped**;
    * otherwise it is **inserted**.

    Returns the counts, so a pipeline run can report what it actually changed
    rather than how many adverts it downloaded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = list(listings)
    connection = connect(path)
    try:
        # Before the schema script: it creates an index over the new column,
        # which an unmigrated table does not have yet.
        migrate(connection)
        connection.executescript(_SCHEMA)
        known_ids = {row["id"] for row in connection.execute("SELECT id FROM listings")}
        # Fingerprint -> the token that already owns it. A listing whose own
        # token is stored keeps its row even if the fingerprint collides,
        # otherwise re-crawling a listing would look like a duplicate of itself.
        owners = {
            row["fingerprint"]: row["id"]
            for row in connection.execute("SELECT fingerprint, id FROM listings")
        }

        inserted = updated = skipped = 0
        batch: list[tuple] = []
        for listing in fresh:
            existing_owner = owners.get(fingerprint(listing))
            if existing_owner is not None and existing_owner != listing.id:
                skipped += 1
                continue
            if listing.id in known_ids:
                updated += 1
            else:
                inserted += 1
                owners[fingerprint(listing)] = listing.id
            batch.append(_row(listing))

        columns = ", ".join((*_INDEXED_COLUMNS, "search_text", "payload"))
        placeholders = ", ".join("?" * (len(_INDEXED_COLUMNS) + 2))
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in (*_INDEXED_COLUMNS[1:], "search_text", "payload")
        )
        written_ids = [row[0] for row in batch]
        with connection:
            # listings_fts is an *external content* index: it stores no text of
            # its own and reads the row back out of `listings` to work out
            # which terms to remove. So a row that is about to be rewritten has
            # to leave the index *before* its text changes underneath it, and
            # by the 'delete' command, which is told the old text explicitly --
            # a plain DELETE re-reads the (already updated) content row, fails
            # to find the terms it indexed, and reports the mismatch as
            # "database disk image is malformed" on a perfectly healthy file.
            stale: list[tuple[int, str]] = []
            for start in range(0, len(written_ids), 500):
                chunk = written_ids[start : start + 500]
                stale += [
                    (row["rowid"], row["search_text"])
                    for row in connection.execute(
                        f"SELECT rowid, search_text FROM listings WHERE id IN ({', '.join('?' * len(chunk))})",
                        chunk,
                    )
                ]
            connection.executemany(
                "INSERT INTO listings_fts (listings_fts, rowid, search_text) VALUES ('delete', ?, ?)",
                stale,
            )
            connection.executemany(
                f"INSERT INTO listings ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                batch,
            )
            # The R*Tree and the FTS index are separate tables with no triggers
            # on them, so an upsert has to maintain both by hand. Deleting the
            # affected rowids first makes the write idempotent whether the row
            # was new or replaced.
            # `id` is _INDEXED_COLUMNS[0], so the batch itself carries the ids.
            # Chunked because SQLite caps the number of bound parameters.
            touched: list[tuple[int]] = []
            for start in range(0, len(written_ids), 500):
                chunk = written_ids[start : start + 500]
                touched += [
                    (row["rowid"],)
                    for row in connection.execute(
                        f"SELECT rowid FROM listings WHERE id IN ({', '.join('?' * len(chunk))})", chunk
                    )
                ]
            connection.executemany("DELETE FROM listings_geo WHERE id = ?", touched)
            connection.executemany(
                "INSERT INTO listings_geo (id, min_lat, max_lat, min_lon, max_lon) "
                "SELECT rowid, lat, lat, lon, lon FROM listings WHERE rowid = ?",
                touched,
            )
            connection.executemany(
                "INSERT INTO listings_fts (rowid, search_text) "
                "SELECT rowid, search_text FROM listings WHERE rowid = ?",
                touched,
            )
            total = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('listing_count', ?)", (str(total),))
        connection.execute("ANALYZE")
        return {"inserted": inserted, "updated": updated, "skipped_duplicate": skipped, "total": total}
    finally:
        connection.close()


def purge_placeholder_prices(path: Path = DEFAULT_DB_PATH) -> int:
    """Delete stored adverts whose price is a placeholder, and report how many.

    Exists as its own operation because a database built before the filter
    landed still holds them, and rebuilding the whole corpus to remove a few
    dozen rows is the wrong trade. See app/data/price_plausibility.py for what
    counts as a placeholder and why they have to go rather than be flagged.
    """
    from app.data.price_plausibility import MIN_PLAUSIBLE_COST_PER_SQM, MIN_PLAUSIBLE_MONTHLY_COST

    connection = connect(path)
    try:
        with connection:
            doomed = [
                (row["rowid"],)
                for row in connection.execute(
                    "SELECT rowid FROM listings WHERE effective_monthly_cost < ? "
                    "OR (area_sqm > 0 AND effective_monthly_cost * 1.0 / area_sqm < ?)",
                    (MIN_PLAUSIBLE_MONTHLY_COST, MIN_PLAUSIBLE_COST_PER_SQM),
                )
            ]
            connection.executemany("DELETE FROM listings_fts WHERE rowid = ?", doomed)
            connection.executemany("DELETE FROM listings_geo WHERE id = ?", doomed)
            connection.executemany("DELETE FROM embeddings WHERE rowid = ?", doomed)
            connection.executemany("DELETE FROM listings WHERE rowid = ?", doomed)
            total = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('listing_count', ?)", (str(total),))
        return len(doomed)
    finally:
        connection.close()


def purge_local_price_outliers(path: Path = DEFAULT_DB_PATH) -> dict:
    """Delete adverts whose price is implausible *for where they stand*.

    The companion to purge_placeholder_prices, which only knows about absolute
    floors. This one measures every listing against the homes within about a
    kilometre of it and removes the ones sitting below a lower confidence
    limit built from the local median and its median absolute deviation --
    see app/data/price_plausibility.py for why the band is adaptive and why it
    is deliberately loose.

    It also writes the measured floors to disk, so the crawler can apply the
    same judgement one advert at a time and these never come back.
    """
    from app.data import price_plausibility as pp

    connection = connect(path)
    try:
        rows = list(
            connection.execute(
                "SELECT rowid, lat, lon, deposit_toman, rent_toman, area_sqm "
                "FROM listings WHERE area_sqm > 0 AND lat IS NOT NULL AND lon IS NOT NULL"
            )
        )
        samples = [
            (row["lat"], row["lon"], pp.cost_per_sqm(row["deposit_toman"], row["rent_toman"], row["area_sqm"]))
            for row in rows
        ]
        floors = pp.local_price_floors([(lat, lon, value) for lat, lon, value in samples if value])
        doomed = [
            (row["rowid"],)
            for row in rows
            if pp.is_local_price_outlier(
                floors, row["lat"], row["lon"], row["deposit_toman"], row["rent_toman"], row["area_sqm"]
            )
        ]
        with connection:
            connection.executemany("DELETE FROM listings_fts WHERE rowid = ?", doomed)
            connection.executemany("DELETE FROM listings_geo WHERE id = ?", doomed)
            connection.executemany("DELETE FROM embeddings WHERE rowid = ?", doomed)
            connection.executemany("DELETE FROM listings WHERE rowid = ?", doomed)
            total = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('listing_count', ?)", (str(total),))
        pp.save_price_floors(floors)
        return {"deleted": len(doomed), "cells_measured": len(floors), "total": total}
    finally:
        connection.close()


def refresh_metro_walk_times(path: Path = DEFAULT_DB_PATH) -> int:
    """Recompute every listing's walk to its nearest metro station.

    Exists because that figure is stored, not derived at query time, so a
    change to how the walk is measured (it is now the street-grid distance,
    not the straight line -- app/spatial/routing.py) leaves a database built
    under the old model quietly disagreeing with the code ranking it. Updates
    the indexed column and the JSON payload together, since both are read.
    """
    from app.spatial.routing import nearest_metro_walk_minutes

    connection = connect(path)
    try:
        updates = []
        for row in connection.execute("SELECT rowid, payload FROM listings"):
            listing = json.loads(row["payload"])
            station, dist_meters, walk_mins = nearest_metro_walk_minutes(listing["lat"], listing["lon"])
            listing["nearest_metro_id"] = station["id"]
            listing["nearest_metro_name"] = station["name"]
            listing["dist_to_metro_meters"] = round(dist_meters, 1)
            listing["metro_walk_mins"] = round(walk_mins, 2)
            updates.append((round(walk_mins, 2), json.dumps(listing, ensure_ascii=False), row["rowid"]))
        with connection:
            connection.executemany(
                "UPDATE listings SET metro_walk_mins = ?, payload = ? WHERE rowid = ?", updates
            )
        connection.execute("ANALYZE")
        return len(updates)
    finally:
        connection.close()


def store_embeddings(vectors: dict[str, list[float]], path: Path = DEFAULT_DB_PATH) -> int:
    """Attach description vectors to listings already in the database.

    Split from ``build`` because embedding the corpus is a paid, slow, network
    step: the database is usable (and the app fully functional bar semantic
    similarity) the moment the rows land, and vectors can be backfilled later.
    """
    connection = connect(path)
    try:
        ids = {row["id"]: row["rowid"] for row in connection.execute("SELECT rowid, id FROM listings")}
        rows = [
            (ids[listing_id], len(vector), array.array("f", vector).tobytes())
            for listing_id, vector in vectors.items()
            if listing_id in ids and vector
        ]
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO embeddings (rowid, dimension, vector) VALUES (?, ?, ?)", rows
            )
        return len(rows)
    finally:
        connection.close()


def load_all(connection: sqlite3.Connection, *, with_embeddings: bool = True) -> Iterator[Listing]:
    """Every listing, vectors folded back in.

    The ranking engine scores the whole candidate set in Python, so the corpus
    is materialised once at startup and kept in memory; the database's job on
    the hot path is narrowing (R*Tree, indexes), not row-by-row fetching.
    """
    sql = (
        "SELECT l.payload AS payload, e.vector AS vector FROM listings AS l LEFT JOIN embeddings AS e USING (rowid)"
        if with_embeddings
        else "SELECT payload AS payload, NULL AS vector FROM listings"
    )
    for row in connection.execute(sql):
        listing = Listing.model_validate_json(row["payload"])
        if row["vector"] is not None:
            listing.embedding = array.array("f", row["vector"]).tolist()
        yield listing


def restore_seed(path: Path = DEFAULT_DB_PATH, seed: Path = SEED_DB_PATH) -> Optional[int]:
    """Unpack the shipped corpus to ``path``; returns its row count, or None.

    None means there was nothing to unpack -- a checkout without the seed file
    -- which is a fact about this deployment, not an error: the caller falls
    back to the synthetic corpus. Anything else that goes wrong (a truncated
    download, no room on the volume) is raised, because silently coming up on
    3,000 invented listings when 21,000 real ones were meant to be there is
    the failure that is hardest to notice.

    Unpacked next to the target and moved into place, so a container killed
    mid-restore leaves no half-written file behind for the next start to find
    and mistake for a database. xz because it is the smallest of the formats
    Python can read with no dependency at all: 114 MB of SQLite becomes 14.

    LZMA is compressed with a 64 MB dictionary; decompressing streams it back
    in 1 MB blocks rather than reading the whole corpus into memory.
    """
    if not seed.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + ".restoring")
    try:
        with lzma.open(seed, "rb") as packed, open(staging, "wb") as out:
            shutil.copyfileobj(packed, out, length=1 << 20)
        os.replace(staging, path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return listing_count(path)


def listing_count(path: Path = DEFAULT_DB_PATH) -> Optional[int]:
    """Row count, or None when there is no usable database at this path."""
    if not path.exists():
        return None
    connection = connect(path, read_only=True)
    try:
        return connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    except sqlite3.DatabaseError:
        return None
    finally:
        connection.close()
