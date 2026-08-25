"""Synthetic listing generation. See docs/DATA_SCHEMA.md section 3 for the
neighborhood distribution rules the generated data follows."""

import random
from typing import NamedTuple

import h3

from app.core.constants import TEHRAN_BBOX
from app.core.models import Listing
from app.core.normalizers import to_persian_digits
from app.core.pricing import calculate_effective_monthly_cost
from app.spatial.transit import find_nearest_metro_station, is_inside_tarh_terafik

H3_RESOLUTION = 8
_COORD_JITTER_DEGREES = 0.015
_LISTING_ID_START = 1000


class NeighborhoodAnchor(NamedTuple):
    names: list[str]
    lat: float
    lon: float
    deposit_range: tuple[int, int]
    rent_range: tuple[int, int]
    area_range: tuple[int, int]
    elevator_probability: float


# docs/DATA_SCHEMA.md SS3.
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


def _jitter_coordinate(anchor_lat: float, anchor_lon: float, rng: random.Random) -> tuple[float, float]:
    lat = anchor_lat + rng.uniform(-_COORD_JITTER_DEGREES, _COORD_JITTER_DEGREES)
    lon = anchor_lon + rng.uniform(-_COORD_JITTER_DEGREES, _COORD_JITTER_DEGREES)
    lat = min(max(lat, TEHRAN_BBOX.min_lat), TEHRAN_BBOX.max_lat)
    lon = min(max(lon, TEHRAN_BBOX.min_lon), TEHRAN_BBOX.max_lon)
    return lat, lon


def _build_description(rng: random.Random) -> str:
    traits = rng.sample(_SOFT_TRAIT_PHRASES, k=rng.randint(2, 4))
    return "واحدی با " + "، ".join(traits) + "."


def _build_title(area_sqm: int, rooms: int, neighborhood: str) -> str:
    return f"{to_persian_digits(area_sqm)} متر، {to_persian_digits(rooms)} خوابه، {neighborhood}"


def generate_synthetic_listings(n: int = 1000, seed: int = 42) -> list[Listing]:
    """Generate n synthetic Tehran listings distributed across the five
    neighborhood anchors from docs/DATA_SCHEMA.md SS3, with derived spatial
    fields computed via the real Tehran transit engine (app/spatial).
    Deterministic for a given seed, so seeded runs are reproducible.
    """
    rng = random.Random(seed)
    listings: list[Listing] = []

    for i in range(n):
        anchor = NEIGHBORHOOD_ANCHORS[i % len(NEIGHBORHOOD_ANCHORS)]
        neighborhood = rng.choice(anchor.names)
        lat, lon = _jitter_coordinate(anchor.lat, anchor.lon, rng)

        deposit_toman = rng.randint(*anchor.deposit_range)
        rent_toman = rng.randint(*anchor.rent_range)
        area_sqm = rng.randint(*anchor.area_range)
        rooms = min(5, max(1, round(area_sqm / 35)))
        total_floors = rng.randint(1, 14)
        floor = rng.randint(0, total_floors)
        has_elevator = rng.random() < anchor.elevator_probability

        station, dist_km, walk_mins = find_nearest_metro_station(lat, lon)
        inside_congestion_zone = is_inside_tarh_terafik(lat, lon)

        listings.append(
            Listing(
                id=f"teh-{_LISTING_ID_START + i}",
                title=_build_title(area_sqm, rooms, neighborhood),
                description=_build_description(rng),
                neighborhood=neighborhood,
                deposit_toman=deposit_toman,
                rent_toman=rent_toman,
                effective_monthly_cost=calculate_effective_monthly_cost(deposit_toman, rent_toman),
                can_convert=rng.random() < 0.85,
                area_sqm=area_sqm,
                rooms=rooms,
                floor=floor,
                total_floors=total_floors,
                has_elevator=has_elevator,
                has_parking=rng.random() < 0.65,
                has_balcony=rng.random() < 0.55,
                has_storage=rng.random() < 0.70,
                building_age_years=rng.randint(0, 30),
                lat=lat,
                lon=lon,
                h3_index=h3.latlng_to_cell(lat, lon, H3_RESOLUTION),
                nearest_metro_id=station["id"],
                nearest_metro_name=station["name"],
                dist_to_metro_meters=dist_km * 1000,
                metro_walk_mins=walk_mins,
                in_tarh_terafik=inside_congestion_zone,
                # No separate Tarh-e Aloodegi (pollution-control) polygon is
                # modeled yet; approximated with the same MVP congestion bbox.
                in_tarh_aloodegi=inside_congestion_zone,
            )
        )

    return listings
