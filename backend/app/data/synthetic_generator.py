"""Synthetic listing generation. See docs/DATA_SCHEMA.md section 3 for the
neighborhood distribution rules the generated data follows."""

import asyncio
import math
import random
from typing import NamedTuple, Optional, Protocol

import h3
from shapely.geometry import Point

from app.core.constants import TEHRAN_BBOX
from app.core.models import Listing
from app.core.normalizers import to_persian_digits
from app.core.pricing import calculate_effective_monthly_cost
from app.spatial.districts import find_district
from app.spatial.neighborhoods import NEIGHBORHOODS, Neighborhood
from app.spatial.transit import find_nearest_metro_station, is_inside_tarh_aloodegi, is_inside_tarh_terafik

H3_RESOLUTION = 8
_LISTING_ID_START = 1000
_EMBEDDING_BATCH_SIZE = 50
# Rejection sampling inside a concave neighborhood polygon; past this many
# misses the polygon is thin enough that its guaranteed-interior
# representative point is a better answer than another retry.
_MAX_POINT_SAMPLE_ATTEMPTS = 40


class EmbeddingClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    generate_embedding method -- lets tests pass a lightweight fake."""

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]: ...


class NeighborhoodAnchor(NamedTuple):
    names: list[str]
    lat: float
    lon: float
    deposit_range: tuple[int, int]
    rent_range: tuple[int, int]
    area_range: tuple[int, int]
    elevator_probability: float


# docs/DATA_SCHEMA.md SS3. These are now *price profiles* keyed by location:
# `names` records which neighborhoods the documented figures were sampled from,
# while a generated listing takes its own name from the real polygon it lands
# in and inherits the pricing of whichever anchor is nearest.
NEIGHBORHOOD_ANCHORS: list[NeighborhoodAnchor] = [
    NeighborhoodAnchor(
        ["سعادت‌آباد", "شهرک غرب"], 35.78, 51.37, (500_000_000, 2_000_000_000), (20_000_000, 80_000_000), (80, 180), 0.90
    ),
    NeighborhoodAnchor(
        ["یوسف‌آباد", "امیرآباد", "فاطمی"], 35.72, 51.40, (200_000_000, 800_000_000), (12_000_000, 35_000_000), (60, 120), 0.60
    ),
    NeighborhoodAnchor(
        ["صادقیه", "پونک", "جنت‌آباد"], 35.73, 51.33, (200_000_000, 600_000_000), (10_000_000, 25_000_000), (55, 110), 0.75
    ),
    NeighborhoodAnchor(
        ["میدان انقلاب", "دانشگاه شریف"], 35.70, 51.36, (100_000_000, 400_000_000), (7_000_000, 18_000_000), (40, 85), 0.40
    ),
    NeighborhoodAnchor(
        ["تهرانپارس", "نارمک"], 35.73, 51.52, (150_000_000, 500_000_000), (8_000_000, 22_000_000), (50, 100), 0.70
    ),
]

_SOFT_TRAIT_PHRASES = [
    "نورگیر عالی",
    "کوچه خلوت",
    "نوساز",
    "بازسازی‌شده",
    "دید باز به کوهستان",
    "همکف بدون پله",
    "سرویس بهداشتی ایرانی و فرنگی",
    "کابینت جدید",
    "پارکینگ اختصاصی",
    "نزدیک پارک",
    "آسانسور جدید",
    "دسترسی عالی به اتوبان",
]


def _sample_point_in(neighborhood: Neighborhood, rng: random.Random) -> tuple[float, float]:
    """A random coordinate genuinely inside the neighborhood's polygon.

    Listings are placed inside real محله boundaries rather than jittered
    around five hand-picked anchors, so that selecting a neighborhood on the
    map -- which filters by polygon containment -- actually returns the
    listings drawn inside that outline.
    """
    for _ in range(_MAX_POINT_SAMPLE_ATTEMPTS):
        lat = rng.uniform(neighborhood.min_lat, neighborhood.max_lat)
        lon = rng.uniform(neighborhood.min_lon, neighborhood.max_lon)
        if neighborhood.polygon.contains(Point(lon, lat)):
            break
    else:
        lat, lon = neighborhood.center_lat, neighborhood.center_lon

    lat = min(max(lat, TEHRAN_BBOX.min_lat), TEHRAN_BBOX.max_lat)
    lon = min(max(lon, TEHRAN_BBOX.min_lon), TEHRAN_BBOX.max_lon)
    return lat, lon


def _nearest_anchor(lat: float, lon: float) -> NeighborhoodAnchor:
    """The price/area profile applied to a neighborhood: the anchor from
    docs/DATA_SCHEMA.md SS3 whose centre is closest to it. The anchors remain
    the documented source of market pricing; geography just decides which one
    a given محله inherits, so north-Tehran polygons stay expensive and
    south/east ones stay cheap without hand-pricing 258 neighborhoods.
    """
    return min(NEIGHBORHOOD_ANCHORS, key=lambda a: math.hypot(a.lat - lat, a.lon - lon))


def _build_description(rng: random.Random) -> str:
    traits = rng.sample(_SOFT_TRAIT_PHRASES, k=rng.randint(2, 4))
    return "واحدی با " + "، ".join(traits) + "."


def _build_title(area_sqm: int, rooms: int, neighborhood: str) -> str:
    return f"{to_persian_digits(area_sqm)} متر، {to_persian_digits(rooms)} خوابه، {neighborhood}"


async def generate_synthetic_listings(client: EmbeddingClient, n: int = 1000, seed: int = 42) -> list[Listing]:
    """Generate n synthetic Tehran listings spread evenly across the 258 real
    محله polygons, priced by the nearest anchor from docs/DATA_SCHEMA.md SS3,
    with derived spatial fields computed via the real Tehran transit engine
    (app/spatial). Deterministic for a given seed, so seeded runs are
    reproducible.

    Each listing's description embedding is precomputed once here (batched)
    and cached on Listing.embedding, so app.search.scoring doesn't have to
    re-embed every candidate listing on every search request.
    """
    rng = random.Random(seed)
    listings: list[Listing] = []

    for i in range(n):
        # Round-robin rather than random choice so every one of the 258
        # neighborhoods is represented -- a neighborhood with no listings
        # would look broken when picked as a search area.
        neighborhood = NEIGHBORHOODS[i % len(NEIGHBORHOODS)]
        lat, lon = _sample_point_in(neighborhood, rng)
        anchor = _nearest_anchor(lat, lon)

        deposit_toman = rng.randint(*anchor.deposit_range)
        rent_toman = rng.randint(*anchor.rent_range)
        area_sqm = rng.randint(*anchor.area_range)
        rooms = min(5, max(1, round(area_sqm / 35)))
        total_floors = rng.randint(1, 14)
        floor = rng.randint(0, total_floors)
        has_elevator = rng.random() < anchor.elevator_probability
        building_age_years = rng.randint(0, 30)
        # Divar advertises رهن کامل with a token monthly rent rather than a
        # zero, so the generated set mirrors that shape -- a `rent == 0` test
        # would find none of them in the real feed either.
        is_full_rahn = rng.random() < 0.12
        if is_full_rahn:
            deposit_toman = deposit_toman + int(rent_toman / 0.03)
            rent_toman = 10_000
        can_convert = (not is_full_rahn) and rng.random() < 0.85

        station, dist_km, walk_mins = find_nearest_metro_station(lat, lon)
        district = find_district(lat, lon)

        listings.append(
            Listing(
                id=f"teh-{_LISTING_ID_START + i}",
                title=_build_title(area_sqm, rooms, neighborhood.title),
                description=_build_description(rng),
                neighborhood=neighborhood.title,
                neighborhood_key=neighborhood.key,
                district=to_persian_digits(district) if district else None,
                deposit_toman=deposit_toman,
                rent_toman=rent_toman,
                effective_monthly_cost=calculate_effective_monthly_cost(deposit_toman, rent_toman),
                can_convert=can_convert,
                convertible_deposit_max_toman=(
                    deposit_toman + int(rent_toman / 0.03 * rng.uniform(0.4, 1.0)) if can_convert else None
                ),
                is_full_rahn=is_full_rahn,
                area_sqm=area_sqm,
                rooms=rooms,
                floor=floor,
                total_floors=total_floors,
                has_elevator=has_elevator,
                has_parking=rng.random() < 0.65,
                has_balcony=rng.random() < 0.55,
                has_storage=rng.random() < 0.70,
                building_age_years=building_age_years,
                # 1405 is the current Iranian year; age is the source of truth
                # here and the year is derived from it, which is the opposite
                # of the real feed (where the ad states the year).
                build_year=1405 - building_age_years,
                image_count=rng.randint(0, 8),
                lat=lat,
                lon=lon,
                h3_index=h3.latlng_to_cell(lat, lon, H3_RESOLUTION),
                nearest_metro_id=station["id"],
                nearest_metro_name=station["name"],
                dist_to_metro_meters=dist_km * 1000,
                metro_walk_mins=walk_mins,
                in_tarh_terafik=is_inside_tarh_terafik(lat, lon),
                in_tarh_aloodegi=is_inside_tarh_aloodegi(lat, lon),
            )
        )

    # Descriptions are assembled from a fixed phrase pool, so across a few
    # thousand listings only a few hundred distinct strings occur. Embedding
    # the distinct ones and sharing the vectors makes the cost of the dataset
    # depend on the phrase pool rather than on the listing count -- which is
    # what lets this be large enough for per-neighborhood search to return
    # more than a handful of results.
    unique_descriptions = list({listing.description for listing in listings})
    vectors: dict[str, list[float]] = {}
    for batch_start in range(0, len(unique_descriptions), _EMBEDDING_BATCH_SIZE):
        batch = unique_descriptions[batch_start : batch_start + _EMBEDDING_BATCH_SIZE]
        embeddings = await asyncio.gather(*(client.generate_embedding(description) for description in batch))
        vectors.update(zip(batch, embeddings))

    for listing in listings:
        listing.embedding = vectors.get(listing.description)

    return listings
