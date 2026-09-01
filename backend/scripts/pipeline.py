"""Crawl -> enrich -> store, as one resumable command.

    python -m scripts.pipeline                      # full run, density-weighted
    python -m scripts.pipeline --target 3000        # smaller sample
    python -m scripts.pipeline --skip-crawl         # re-enrich and re-store what is on disk
    python -m scripts.pipeline --rebuild            # replace the corpus instead of merging
    python -m scripts.pipeline --embed              # also backfill description vectors

Until now the three stages were three commands run by hand, which meant the
database could silently be a crawl behind the JSON, and the neighborhood
quality index a corpus behind the database. Running them as one pipeline makes
that impossible: every stage's output is the next stage's input, in order,
inside a single invocation.

Duplicates are handled at the stage where each kind of duplicate is visible:

  * the crawler skips tokens it has already fetched (``crawled_tokens.json``);
  * ``database.upsert`` skips *reposts* -- the same property advertised again
    under a fresh token -- by fingerprint, and updates a row whose own token
    comes round again, because its price or photos may have moved.

The default is therefore a merge, not a rebuild: a nightly run adds what is
new and refreshes what changed, without discarding a corpus that took hours to
collect. ``--rebuild`` is the explicit way to say "this crawl replaces the old
one".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data import database  # noqa: E402
from app.data.pipelines.divar_preprocess import PROCESSED_PATH, RAW_CRAWL_PATH, run as preprocess, to_listing  # noqa: E402
from app.llm.client import OpenRouterClient, flush_embedding_cache  # noqa: E402

_CRAWLER = Path(__file__).resolve().parent.parent.parent / "crawler" / "divar-crawler.py"
_QUALITY_SCRIPT = Path(__file__).resolve().parent / "build_neighborhood_quality.py"


def _stage(name: str) -> float:
    print(f"\n=== {name} ===", flush=True)
    return time.perf_counter()


def crawl(target: int, districts: int, probe: bool, uniform: bool) -> None:
    command = [sys.executable, str(_CRAWLER), "--target", str(target)]
    if districts:
        command += ["--districts", str(districts)]
    if probe:
        command.append("--probe")
    if uniform:
        command.append("--uniform")
    # Streamed rather than captured: a city-wide crawl runs for hours and its
    # progress log is the only way to tell a slow run from a stuck one.
    subprocess.run(command, check=True)


async def embed(listings: list) -> int:
    client = OpenRouterClient()
    try:
        vectors: dict[str, list[float]] = {}
        for index, listing in enumerate(listings, start=1):
            text = f"{listing.title}\n{listing.description}"
            vectors[listing.id] = await client.generate_embedding(text)
            if index % 200 == 0:
                print(f"  embedded {index}/{len(listings)}", flush=True)
        flush_embedding_cache()
        return database.store_embeddings(vectors)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, default=10_000, help="listings to sample city-wide")
    parser.add_argument("--districts", type=int, default=0, help="limit discovery to N district shards")
    parser.add_argument("--probe", action="store_true", help="re-measure district posting density first")
    parser.add_argument("--uniform", action="store_true", help="equal quota per district")
    parser.add_argument("--skip-crawl", action="store_true", help="use the crawl already on disk")
    parser.add_argument("--rebuild", action="store_true", help="replace the corpus instead of merging into it")
    parser.add_argument("--embed", action="store_true", help="backfill description vectors (slow, paid)")
    parser.add_argument("--db", type=Path, default=database.DEFAULT_DB_PATH)
    args = parser.parse_args()

    if not args.skip_crawl:
        started = _stage("1/4 crawl")
        crawl(args.target, args.districts, args.probe, args.uniform)
        print(f"crawl finished in {time.perf_counter() - started:.0f}s")
    elif not RAW_CRAWL_PATH.exists():
        raise SystemExit(f"--skip-crawl was given but {RAW_CRAWL_PATH} does not exist")

    started = _stage("2/4 enrich")
    summary = preprocess()
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    print(f"enrichment finished in {time.perf_counter() - started:.1f}s")

    started = _stage("3/4 store")
    records = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    listings = [to_listing(record) for record in records]
    if args.rebuild or database.listing_count(args.db) is None:
        total = database.build(listings, args.db)
        print(f"rebuilt {args.db.name} with {total} listings")
    else:
        # Purged first, so a database built before the placeholder rule landed
        # is cleaned by the same run that adds to it.
        purged = database.purge_placeholder_prices(args.db)
        if purged:
            print(f"purged {purged} adverts with a placeholder price")
        # The same rule the crawler and the enricher apply, run once more over
        # the stored corpus: an advert whose effective monthly cost sits far
        # below what its own surroundings charge is a "price by phone" listing,
        # not a bargain. Measuring it here as well means a database built
        # before the rule landed is cleaned by the run that adds to it, and
        # the per-cell floors the crawler reads are re-measured against the
        # corpus as it actually stands.
        outliers = database.purge_local_price_outliers(args.db)
        if outliers["deleted"]:
            print(
                f"purged {outliers['deleted']} adverts priced far below their surroundings "
                f"({outliers['cells_measured']} cells measured)"
            )
        print(json.dumps(database.upsert(listings, args.db), ensure_ascii=False))
    print(f"storage finished in {time.perf_counter() - started:.1f}s")

    started = _stage("4/4 neighborhood quality index")
    subprocess.run([sys.executable, str(_QUALITY_SCRIPT)], check=True)
    print(f"quality index finished in {time.perf_counter() - started:.1f}s")

    if args.embed:
        started = _stage("5/5 embeddings")
        stored = asyncio.run(embed(listings))
        print(f"stored {stored} vectors in {time.perf_counter() - started:.0f}s")

    print(f"\npipeline complete -- {database.listing_count(args.db)} listings in {args.db.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
