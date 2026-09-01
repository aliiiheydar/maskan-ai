"""Build backend/app/data/maskan.db from the processed Divar corpus.

    python -m scripts.build_database                 # rows + indexes only
    python -m scripts.build_database --embed         # also backfill description vectors
    python -m scripts.build_database --synthetic 3000

Embedding is a separate flag because it is the one slow, paid step: the app is
fully usable without it (semantic similarity simply contributes nothing to the
score), so the default build stays offline and takes a couple of seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.models import Listing  # noqa: E402
from app.data import database, divar_preprocess  # noqa: E402

_EMBED_BATCH = 32


def _load_processed() -> list[Listing]:
    path = divar_preprocess.PROCESSED_PATH
    if not path.exists():
        raise SystemExit(
            f"{path.name} is missing. Run `python -m app.data.divar_preprocess` first "
            "to enrich the raw crawl."
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    return [divar_preprocess.to_listing(record) for record in records]


async def _load_synthetic(count: int) -> list[Listing]:
    from app.data.synthetic_generator import generate_synthetic_listings
    from app.llm.client import OpenRouterClient

    client = OpenRouterClient()
    try:
        return await generate_synthetic_listings(client, count)
    finally:
        await client.close()


async def _embed(listings: list[Listing]) -> dict[str, list[float]]:
    from app.llm.client import OpenRouterClient, flush_embedding_cache

    client = OpenRouterClient()
    vectors: dict[str, list[float]] = {}
    try:
        # Descriptions are embedded, not titles: the title is a restatement of
        # the structured fields the filters already handle, while the
        # description is where the soft preferences ("نورگیر", "کوچه خلوت")
        # actually live.
        texts = [listing.description or listing.title for listing in listings]
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = texts[start : start + _EMBED_BATCH]
            results = await asyncio.gather(*(client.generate_embedding(text) for text in batch))
            for listing, vector in zip(listings[start : start + _EMBED_BATCH], results):
                vectors[listing.id] = vector
            print(f"  embedded {min(start + _EMBED_BATCH, len(texts))}/{len(texts)}", end="\r", flush=True)
        flush_embedding_cache()
    finally:
        await client.close()
    print()
    return vectors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true", help="backfill description embeddings (network, paid)")
    parser.add_argument("--synthetic", type=int, default=0, help="build from N generated listings instead of the crawl")
    parser.add_argument("--db", type=Path, default=database.DEFAULT_DB_PATH)
    args = parser.parse_args()

    started = time.perf_counter()
    listings = asyncio.run(_load_synthetic(args.synthetic)) if args.synthetic else _load_processed()
    print(f"loaded {len(listings)} listings in {time.perf_counter() - started:.1f}s")

    started = time.perf_counter()
    count = database.build(listings, args.db)
    print(f"wrote {count} rows + R*Tree + FTS to {args.db} in {time.perf_counter() - started:.1f}s")

    if args.embed:
        vectors = asyncio.run(_embed(listings))
        print(f"stored {database.store_embeddings(vectors, args.db)} embeddings")

    print(f"database size: {args.db.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
