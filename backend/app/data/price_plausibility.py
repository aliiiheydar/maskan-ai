"""Rejecting ads that carry a placeholder price instead of a real one.

A widespread habit in the Iranian market: rather than publish the price, the
advertiser types a token figure -- ودیعه ۱٬۰۰۰ تومان، اجاره ۱٬۰۰۰ تومان -- so
that anyone interested has to phone and ask. The listing is real; its price is
not. Left in the corpus these ads are corrosive out of all proportion to their
number, because every one of them looks like the cheapest home in Tehran:
they win the budget criterion outright, sit at the very top of the ranking,
and are the first thing a user sees.

There is no flag for them in Divar's data, so they are recognised by the only
thing that gives them away -- a price no real Tehran lease could carry. Two
independent floors, either of which is enough:

  * An absolute floor on the Tabdil-normalised monthly cost. Measured on the
    6,392-listing crawl, the corpus has 41 ads below 1,000,000 Tomans/month
    and then a clean gap: the 0.5th percentile sits at 103,000 and the 1st at
    1,650,000. Nothing real lives in between.

  * A floor on cost per square metre, which catches the other shape of the
    same trick -- a plausible-looking اجاره ۱۰٬۰۰۰٬۰۰۰ attached to a 400-متر
    penthouse. The same gap appears here: the 1st percentile is 35,000
    Tomans/m2 and the 1.5th is 103,000.

Both thresholds sit an order of magnitude under the cheapest genuine listing,
so they cost real inventory nothing. The set they remove is dominated by
همخانه (roommate-wanted), پانسیون and اجارهٔ پارکینگ ads, which are not
apartment leases at all.
"""

import json
from pathlib import Path
from typing import Optional

from app.core import paths
from app.core import constants

# Tomans per month, Tabdil-normalised (rent + 3% of deposit). The cheapest
# genuine lease in the crawl is comfortably above this.
MIN_PLAUSIBLE_MONTHLY_COST = 1_000_000

# Tomans per month per square metre, same normalisation.
MIN_PLAUSIBLE_COST_PER_SQM = 100_000


def effective_monthly_cost(deposit: Optional[int], rent: Optional[int]) -> int:
    return int((rent or 0) + (deposit or 0) * constants.TABDIL_RATE)


def is_placeholder_price(deposit: Optional[int], rent: Optional[int], area_sqm: Optional[int]) -> bool:
    """True when the advertised figures cannot be this home's actual price."""
    cost = effective_monthly_cost(deposit, rent)
    if cost < MIN_PLAUSIBLE_MONTHLY_COST:
        return True
    # Area is only used to *add* a rejection: a listing with no usable area is
    # judged on the absolute floor alone rather than dropped for lack of data.
    if area_sqm and area_sqm > 0 and cost / area_sqm < MIN_PLAUSIBLE_COST_PER_SQM:
        return True
    return False


def is_placeholder_row(row: dict, floors: Optional[dict] = None) -> bool:
    """The same test against a raw crawl row, for filtering during a crawl.

    ``floors`` is the persisted local price map (see load_price_floors); when
    it is supplied and the row is geolocated, the row is also measured against
    the homes around it, which is what catches the placeholder priced
    plausibly for the city but not for its own street.
    """
    deposit, rent, area = row.get("deposit_toman"), row.get("rent_toman"), row.get("area_sqm")
    if is_placeholder_price(deposit, rent, area):
        return True
    lat, lon = row.get("lat"), row.get("lon")
    if floors and lat is not None and lon is not None:
        return is_local_price_outlier(floors, float(lat), float(lon), deposit, rent, area)
    return False


# --------------------------------------------------------------------------
# Spatially adaptive floor
# --------------------------------------------------------------------------
#
# The absolute floors above catch the blatant ودیعه ۱۰۰۰ ads. They cannot
# catch the same trick told more quietly: 300 million ودیعه on a flat in
# زعفرانیه is a perfectly ordinary figure in Tehran and an obvious placeholder
# *there*. What gives those away is not the number, it is the number next to
# its neighbours -- so the second test compares every advert with the homes
# around it on the map and asks whether its cost per square metre could
# plausibly have come from the same market.
#
# The band is adaptive rather than a fixed percentage because neighbourhoods
# genuinely differ in how tight their prices are: a uniform block of new
# towers has a narrow spread and a district mixing old walk-ups with new
# builds has a wide one, and a fixed "40% below the median" would clear the
# first of real listings while letting the second's placeholders through. The
# floor is therefore the local median scaled down by the local *dispersion*,
# measured with the median absolute deviation.
#
# MAD rather than the standard deviation on purpose: the whole point is that
# the sample is contaminated by the very outliers being looked for, and one
# 1,000-Toman advert moves a standard deviation enormously while moving a MAD
# not at all.
#
# There are honest reasons a home is cheaper than its neighbours -- a ground
# floor on a main road, a tired building, a landlord in a hurry -- so the band
# is deliberately loose. It sits at roughly a quarter of the local median for
# a typical spread, which is below anything the market explains and above
# nothing real.

import math
import statistics
from collections import defaultdict

#: Grid cell for "the homes around it", in degrees (~1.1 km square). Large
#: enough that a cell holds a usable sample, small enough that its listings
#: are genuinely the same local market.
_NEIGHBORHOOD_CELL_DEG = 0.01

#: Below this many comparable listings a cell says nothing: the median of four
#: adverts is not a market reading, and judging an advert against it would
#: delete real homes. Those listings fall back to the absolute floors alone.
MIN_LOCAL_SAMPLE = 12

#: The floor is median - this many MADs. 3 MADs is ~2 standard deviations for
#: a normal spread; combined with the absolute cap below it lands around a
#: quarter of the local median.
LOCAL_MAD_MULTIPLIER = 3.0

#: However wide the local spread, the floor never rises above this fraction of
#: the local median (a sanity ceiling: a cell with a huge MAD must not start
#: deleting merely-cheap homes) nor falls below the other (a cell with almost
#: no spread must not start deleting anything at all).
LOCAL_FLOOR_MAX_FRACTION = 0.35
LOCAL_FLOOR_MIN_FRACTION = 0.12


def _cell_key(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / _NEIGHBORHOOD_CELL_DEG)), int(math.floor(lon / _NEIGHBORHOOD_CELL_DEG))


def cost_per_sqm(deposit: Optional[int], rent: Optional[int], area_sqm: Optional[int]) -> Optional[float]:
    if not area_sqm or area_sqm <= 0:
        return None
    return effective_monthly_cost(deposit, rent) / area_sqm


def local_price_floors(samples: list[tuple[float, float, float]]) -> dict[tuple[int, int], float]:
    """Per-cell lower confidence limit on cost/m2, from (lat, lon, cost_per_sqm).

    Returns only the cells that carry enough listings to have an opinion; a
    caller that finds no entry for a listing's cell should leave that listing
    alone rather than guess.
    """
    by_cell: dict[tuple[int, int], list[float]] = defaultdict(list)
    for lat, lon, value in samples:
        if value and value > 0:
            by_cell[_cell_key(lat, lon)].append(value)

    floors: dict[tuple[int, int], float] = {}
    for cell, values in by_cell.items():
        if len(values) < MIN_LOCAL_SAMPLE:
            continue
        median = statistics.median(values)
        mad = statistics.median([abs(v - median) for v in values])
        floor = median - LOCAL_MAD_MULTIPLIER * mad
        floors[cell] = max(
            LOCAL_FLOOR_MIN_FRACTION * median,
            min(floor, LOCAL_FLOOR_MAX_FRACTION * median),
        )
    return floors


def is_local_price_outlier(
    floors: dict[tuple[int, int], float],
    lat: float,
    lon: float,
    deposit: Optional[int],
    rent: Optional[int],
    area_sqm: Optional[int],
) -> bool:
    """True when this advert is too cheap for where it stands to be a real price."""
    value = cost_per_sqm(deposit, rent, area_sqm)
    if value is None:
        return False
    floor = floors.get(_cell_key(lat, lon))
    return floor is not None and value < floor


# --------------------------------------------------------------------------
# The floors, persisted for the crawler
# --------------------------------------------------------------------------
#
# The local floor is a corpus-wide measurement, and the crawler runs one
# advert at a time with no corpus in front of it. So the measurement is taken
# once against the built database (app.data.database.purge_local_price_outliers
# writes it) and read back here, which lets a crawl reject a placeholder at
# the moment it is fetched instead of letting it into the store and cleaning
# up afterwards. Absent file, absent opinion: the crawl falls back to the
# absolute floors, exactly as it behaved before.

FLOORS_PATH = paths.asset("local_price_floors.json")


def save_price_floors(floors: dict[tuple[int, int], float], path: Path = FLOORS_PATH) -> int:
    path.write_text(
        json.dumps({f"{row},{col}": round(value, 2) for (row, col), value in floors.items()}, indent=0),
        encoding="utf-8",
    )
    return len(floors)


def load_price_floors(path: Path = FLOORS_PATH) -> dict[tuple[int, int], float]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {(int(key.split(",")[0]), int(key.split(",")[1])): float(value) for key, value in raw.items()}
