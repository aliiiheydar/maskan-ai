"""Neighborhood desirability index (کیفیت محله), on a 0..1 scale.

Two flats with the same price, size and metro walk are not equally good homes
if one is in زعفرانیه and the other in a district with worse air, older stock
and fewer amenities. That difference is real, renters weight it heavily, and
nothing else in the ranking captures it: `value` deliberately measures price
*relative to the neighborhood's own median*, so it is blind by construction to
whether the neighborhood itself is a desirable place to live.

The index is precomputed offline by ``scripts/build_neighborhood_quality.py``
and read here. Two components go into it:

  * **prestige** -- the neighborhood's price level per square metre, shrunk
    toward its municipal district's published market figure so that a محله with
    six listings is not ranked off six listings. Price is the only signal that
    aggregates everything people mean by "a good area" -- schools, air, safety,
    shops, green space -- into one number the market has already agreed on.
  * **modernity** -- median building age of its stock, which is what separates
    a district of 1970s walk-ups from one of serviced towers at the same price.

Keeping this in a generated file rather than computing it per request matters
for the same reason MarketBaselines is precomputed: it is a corpus-wide
aggregate, and recomputing it inside the scoring loop would dominate the
search.
"""

import json
from functools import lru_cache
from typing import Optional
from app.core import paths

_QUALITY_PATH = paths.asset("neighborhood_quality.json")

# What a neighborhood with no entry scores. Deliberately the middle of the
# scale and not 0: an unmeasured neighborhood should be neutral in the ranking,
# never penalised for our missing data.
NEUTRAL_QUALITY: float = 0.5


@lru_cache(maxsize=1)
def _index() -> dict[str, float]:
    """{neighborhood_key: score}, or {} before the index has been built."""
    if not _QUALITY_PATH.exists():
        return {}
    payload = json.loads(_QUALITY_PATH.read_text(encoding="utf-8"))
    return {str(key): float(entry["score"]) for key, entry in payload.get("neighborhoods", {}).items()}


@lru_cache(maxsize=1)
def details() -> dict[str, dict]:
    """The full record per neighborhood -- score, prestige, modernity, sample
    size and district -- for explaining a ranking rather than scoring it."""
    if not _QUALITY_PATH.exists():
        return {}
    payload = json.loads(_QUALITY_PATH.read_text(encoding="utf-8"))
    return {str(key): dict(entry) for key, entry in payload.get("neighborhoods", {}).items()}


def score_for(neighborhood_key: Optional[str]) -> float:
    """The 0..1 desirability of a neighborhood, neutral where unknown."""
    if not neighborhood_key:
        return NEUTRAL_QUALITY
    return _index().get(str(neighborhood_key), NEUTRAL_QUALITY)


def is_available() -> bool:
    """False in a checkout where the index has never been built -- callers use
    this to keep the criterion out of the weighting rather than feeding every
    listing the same neutral 0.5, which would flatten the score range."""
    return bool(_index())
