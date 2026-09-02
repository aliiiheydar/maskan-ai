"""Pack the built corpus into the compressed seed that ships with the repo.

    python -m scripts.pack_seed

Run this after a crawl has grown or refreshed the database and the new corpus
is the one other people should get. It is the only step that puts a large
binary into the repository, so it is a deliberate command rather than part of
`scripts.pipeline`: a nightly merge should not rewrite a 14 MB tracked file.

The database is checkpointed and VACUUMed first. A live SQLite in WAL mode
keeps recent writes in maskan.db-wal, and the seed is one file -- without the
checkpoint, whatever was still in the WAL would simply be missing from the
copy everyone else receives.
"""

from __future__ import annotations

import lzma
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data import database  # noqa: E402


def main() -> int:
    source = database.DEFAULT_DB_PATH
    if not source.exists():
        raise SystemExit(f"{source} does not exist. Build the corpus first (python -m scripts.pipeline).")

    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    finally:
        connection.close()

    target = database.SEED_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    # preset 9|EXTREME takes about a minute on this corpus and saves ~3 MB over
    # the default; the file is written once and cloned by everyone, so the
    # minute is bought back on the first `git clone`.
    with open(source, "rb") as raw, lzma.open(target, "wb", preset=9 | lzma.PRESET_EXTREME) as packed:
        shutil.copyfileobj(raw, packed, length=1 << 20)

    rows = database.listing_count(source) or 0
    print(
        f"packed {rows} listings: {source.stat().st_size / 1e6:.0f} MB -> "
        f"{target.stat().st_size / 1e6:.1f} MB in {time.perf_counter() - started:.0f}s"
    )
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
