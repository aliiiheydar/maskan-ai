"""Build app/data/neighborhood_quality.json -- the 0..1 desirability index.

    python -m scripts.build_neighborhood_quality

Reads the processed corpus (or the SQLite build, whichever is present) plus
the published per-district price priors in ``district_prestige.json``, and
writes one score per neighborhood polygon. Both inputs are read-only; the
output is a new generated file.

Method, in order:

  1. Per neighborhood, the median *effective monthly cost per square metre* --
     rent plus 3% of the deposit, over area. This is the rental market's own
     verdict on how desirable the location is, and unlike a raw rent it is
     comparable between a studio and a penthouse.

  2. Shrink that toward the neighborhood's municipal district using
     ``(n*local + K*district) / (n + K)``. A محله with 200 listings keeps
     essentially its own figure; one with three is pulled almost entirely onto
     the district's. This is what stops a single luxury tower in a modest
     neighborhood from crowning it, without having to throw away small samples.

  3. Convert to a percentile rank across neighborhoods, so the score is a
     position in Tehran rather than a Toman figure that drifts with inflation.

  4. Blend with a modernity term (percentile rank of median build year),
     because "a good area" is partly about the age of the stock and price
     alone does not separate an old expensive district from a new one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import constants  # noqa: E402
from app.data import database  # noqa: E402
from app.data.divar_preprocess import PROCESSED_PATH, to_listing  # noqa: E402
from app.spatial import districts as districts_module  # noqa: E402
from app.spatial import neighborhoods  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
_PRIORS_PATH = _DATA_DIR / "district_prestige.json"
OUTPUT_PATH = _DATA_DIR / "neighborhood_quality.json"

# Shrinkage strength: the number of listings at which a neighborhood's own
# median and its district's prior count equally. Eight is roughly where a
# median stops being one outlier away from moving -- the same threshold
# MarketBaselines uses to decide a neighborhood median is worth trusting.
SHRINKAGE_K = 8.0

# How the two components combine. Price carries most of it because it is the
# aggregate the market has already formed over everything else; modernity is
# the part price alone cannot express -- two districts at the same price where
# one is 1970s walk-ups and the other is serviced towers.
WEIGHT_PRESTIGE = 0.72
WEIGHT_MODERNITY = 0.28


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """Map each key onto its rank in [0, 1], ties sharing the same rank."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: item[1])
    if len(ordered) == 1:
        return {ordered[0][0]: 0.5}
    ranks: dict[str, float] = {}
    for position, (key, _) in enumerate(ordered):
        ranks[key] = position / (len(ordered) - 1)
    # Equal values must not receive different ranks, or the index would encode
    # the corpus's arbitrary ordering as a quality difference.
    by_value: dict[float, list[str]] = {}
    for key, value in values.items():
        by_value.setdefault(value, []).append(key)
    for tied in by_value.values():
        if len(tied) > 1:
            shared = sum(ranks[key] for key in tied) / len(tied)
            for key in tied:
                ranks[key] = shared
    return ranks


def _load_listings() -> list:
    """Prefer the processed JSON; fall back to whatever is already in SQLite."""
    if PROCESSED_PATH.exists():
        records = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
        return [to_listing(record) for record in records]
    if database.listing_count():
        return database.load_all()
    raise SystemExit(
        "No corpus found. Run `python -m app.data.divar_preprocess` or "
        "`python -m scripts.build_database` first."
    )


def _district_priors() -> dict[str, float]:
    payload = json.loads(_PRIORS_PATH.read_text(encoding="utf-8"))
    return {str(name): float(value) for name, value in payload["districts"].items()}


def _district_of(neighborhood: neighborhoods.Neighborhood) -> Optional[str]:
    return districts_module.find_district(neighborhood.center_lat, neighborhood.center_lon)


def build() -> dict:
    listings = _load_listings()
    priors = _district_priors()

    cost_samples: dict[str, list[float]] = {}
    year_samples: dict[str, list[int]] = {}
    for listing in listings:
        if not listing.neighborhood_key or listing.area_sqm <= 0:
            continue
        per_sqm = (listing.rent_toman + listing.deposit_toman * constants.TABDIL_RATE) / listing.area_sqm
        cost_samples.setdefault(listing.neighborhood_key, []).append(per_sqm)
        if listing.build_year:
            year_samples.setdefault(listing.neighborhood_key, []).append(listing.build_year)

    # The district priors are quoted as sale price per m2 and the corpus is
    # rent per m2, so they live on different scales. Rescaling the priors onto
    # the corpus's own scale -- by matching their means over the neighborhoods
    # where both exist -- is what lets the two be averaged at all.
    prior_by_key: dict[str, float] = {}
    for neighborhood in neighborhoods.NEIGHBORHOODS:
        district = _district_of(neighborhood)
        if district and district in priors:
            prior_by_key[neighborhood.key] = priors[district]

    shared = [key for key in cost_samples if key in prior_by_key and len(cost_samples[key]) >= 5]
    if shared:
        corpus_mean = sum(median(cost_samples[key]) for key in shared) / len(shared)
        prior_mean = sum(prior_by_key[key] for key in shared) / len(shared)
        scale = corpus_mean / prior_mean if prior_mean else 1.0
    else:
        scale = 1.0

    blended: dict[str, float] = {}
    modernity_input: dict[str, float] = {}
    sample_sizes: dict[str, int] = {}
    district_by_key: dict[str, Optional[str]] = {}

    for neighborhood in neighborhoods.NEIGHBORHOODS:
        key = neighborhood.key
        district_by_key[key] = _district_of(neighborhood)
        prior = prior_by_key.get(key)
        observed = cost_samples.get(key, [])
        sample_sizes[key] = len(observed)

        local = median(observed) if observed else None
        scaled_prior = prior * scale if prior is not None else None

        if local is not None and scaled_prior is not None:
            n = len(observed)
            blended[key] = (n * local + SHRINKAGE_K * scaled_prior) / (n + SHRINKAGE_K)
        elif local is not None:
            blended[key] = local
        elif scaled_prior is not None:
            blended[key] = scaled_prior
        # A neighborhood with neither is left out entirely and scores the
        # neutral 0.5 at read time, rather than being given a made-up number.

        years = year_samples.get(key)
        if years:
            modernity_input[key] = float(median(years))

    prestige = _percentile_ranks(blended)
    modernity = _percentile_ranks(modernity_input)

    # A neighborhood whose listings never stated a build year borrows its
    # district's median instead of being scored on prestige alone: dropping the
    # modernity term for it would let an unmeasured neighborhood outrank a
    # measured peer in the same district purely by having no data.
    district_modernity: dict[str, list[float]] = {}
    for key, rank in modernity.items():
        district = district_by_key.get(key)
        if district:
            district_modernity.setdefault(district, []).append(rank)

    entries: dict[str, dict] = {}
    for key, prestige_rank in prestige.items():
        measured = modernity.get(key)
        district = district_by_key.get(key)
        peers = district_modernity.get(district or "", [])
        modernity_rank = measured if measured is not None else (median(peers) if peers else 0.5)
        score = WEIGHT_PRESTIGE * prestige_rank + WEIGHT_MODERNITY * modernity_rank
        neighborhood = neighborhoods.get(key)
        entries[key] = {
            "title": neighborhood.title if neighborhood else "",
            "district": district_by_key.get(key),
            "score": round(score, 4),
            "prestige": round(prestige_rank, 4),
            "modernity": round(modernity_rank, 4),
            "modernity_is_estimated": measured is None,
            "cost_per_sqm": round(blended[key]),
            "sample_size": sample_sizes.get(key, 0),
        }

    return {
        "_comment": (
            "Generated by scripts/build_neighborhood_quality.py. score is 0..1 desirability "
            "(higher = more sought-after), blending a district-shrunk price percentile with "
            "a building-age percentile. Regenerate after every corpus rebuild."
        ),
        "weights": {"prestige": WEIGHT_PRESTIGE, "modernity": WEIGHT_MODERNITY},
        "shrinkage_k": SHRINKAGE_K,
        "neighborhoods": dict(sorted(entries.items(), key=lambda item: -item[1]["score"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    payload = build()
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ranked = list(payload["neighborhoods"].items())
    print(f"wrote {len(ranked)} neighborhood scores -> {args.out.name}")
    print("top:", "، ".join(f"{entry['title']} {entry['score']:.2f}" for _, entry in ranked[:6]))
    print("bottom:", "، ".join(f"{entry['title']} {entry['score']:.2f}" for _, entry in ranked[-6:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
