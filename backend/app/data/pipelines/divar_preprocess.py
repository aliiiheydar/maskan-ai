"""Turn the raw Divar crawl into the enriched corpus the app actually queries.

The crawl is a mixture of two very different kinds of evidence and the whole
point of this module is to keep them apart:

* **Reliable fields** -- what Divar itself stored as typed data: the deposit,
  the rent, the area, the ``مشخصات`` attribute table, the geo point. These are
  taken as-is.
* **Text fields** -- the title and the free-form Persian description, where the
  advertiser says everything Divar never asked them for. These are mined only
  to *fill holes*, never to overwrite a reliable value.

Every listing therefore carries a ``provenance`` map saying, per field, which
of the two a value came from, so the detail page can present a text-derived
"۲ خوابه" differently from one Divar itself recorded -- the same way Divar
separates its own attribute table from the ad copy.

The raw crawl (``crawler/divar_listings.json``) is opened read-only and never
written back; the result is a *new* file, ``processed_listings.json``.

Run it with::

    python -m app.data.pipelines.divar_preprocess
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import h3

from app.core import paths
from app.core.constants import TEHRAN_BBOX
from app.core.shared_living import is_not_a_home
from app.core.models import Listing
from app.core.normalizers import normalize_persian_text, parse_persian_numbers, to_persian_digits
from app.core.pricing import calculate_effective_monthly_cost
from app.spatial import neighborhoods as nb
from app.spatial.districts import find_district
from app.spatial.transit import find_nearest_metro_station, is_inside_tarh_aloodegi, is_inside_tarh_terafik
from app.data.price_plausibility import (
    is_placeholder_price,
    is_local_price_outlier,
    local_price_floors,
    save_price_floors,
)

H3_RESOLUTION = 8
CURRENT_JALALI_YEAR = 1405

RAW_CRAWL_PATH = paths.PROJECT_ROOT / "crawler" / "divar_listings.json"
PROCESSED_PATH = paths.asset("processed_listings.json")
# Divar names our polygon set has no equivalent for, mapped onto the polygon
# their listings actually fall inside. Written as a *separate* file so the two
# curated sources (matched_neighborhoods.geojson, paired_neighborhoods.json)
# stay byte-for-byte untouched; app.spatial.neighborhoods merges it in at load.
ALIASES_PATH = paths.asset("neighborhood_aliases.json")

# Areas outside this band are data errors, not unusual apartments (the crawl
# contains a "115115 متر" row). They are re-derived from the text if possible
# and flagged either way.
_MIN_PLAUSIBLE_AREA = 15
_MAX_PLAUSIBLE_AREA = 2000


def _norm(text: Optional[str]) -> str:
    return normalize_persian_text(parse_persian_numbers(text or ""))


# --------------------------------------------------------------------------
# Text miners. Each returns None when the text says nothing, so the caller can
# tell "the ad is silent" from "the ad says zero".
# --------------------------------------------------------------------------

# "بدون اتاق" / "فاقد خواب" / "سوئیت" all describe the same thing: no bedroom.
_NO_ROOM = re.compile(r"(بدون\s*(اتاق|خواب)|فاقد\s*(اتاق|خواب)|بدون\s*اطاق|سوئیت|سوییت)")
_ROOM_WORDS = {"یک": 1, "تک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5}
_ROOM_DIGIT = re.compile(r"(\d+)\s*(?:عدد\s*)?(?:اتاق|اطاق|خواب)")
_ROOM_WORD = re.compile(r"(یک|تک|دو|سه|چهار|پنج)\s*(?:اتاق|اطاق|خواب)")


def extract_rooms(text: str) -> Optional[int]:
    if _NO_ROOM.search(text):
        return 0
    match = _ROOM_DIGIT.search(text)
    if match:
        rooms = int(match.group(1))
        return rooms if 0 <= rooms <= 10 else None
    match = _ROOM_WORD.search(text)
    if match:
        return _ROOM_WORDS[match.group(1)]
    return None


# Divar's own طبقه attribute is often "3 از 5" -- the building height is right
# there in a reliable field, it just needs splitting out.
_FLOOR_OF_TOTAL = re.compile(r"(-?\d+)\s*از\s*(\d+)")
_TOTAL_FLOORS_TEXT = re.compile(r"(?:از|در|ساختمان)\s*(\d{1,2})\s*طبقه|(\d{1,2})\s*طبقه\s*(?:ساختمان)?")


def extract_floor_pair(raw: str) -> tuple[Optional[int], Optional[int]]:
    """(floor, total_floors) out of a طبقه attribute value."""
    text = _norm(raw)
    match = _FLOOR_OF_TOTAL.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    if re.fullmatch(r"-?\d+", text.strip()):
        return int(text.strip()), None
    if "همکف" in text:
        return 0, None
    if "زیرزمین" in text or "زیر همکف" in text:
        return -1, None
    return None, None


def extract_total_floors(text: str) -> Optional[int]:
    for match in _TOTAL_FLOORS_TEXT.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw and 1 <= int(raw) <= 40:
            return int(raw)
    return None


_AREA_TEXT = re.compile(r"(\d{2,4})\s*(?:متر|متری|مترمربع|متر مربع)")


def extract_area(text: str) -> Optional[int]:
    for match in _AREA_TEXT.finditer(text):
        area = int(match.group(1))
        if _MIN_PLAUSIBLE_AREA <= area <= _MAX_PLAUSIBLE_AREA:
            return area
    return None


def _mentions(text: str, positives: Iterable[str], negatives: Iterable[str] = ()) -> Optional[bool]:
    """True/False when the ad speaks about a feature, None when it is silent.

    Negatives are checked first: "بدون پارکینگ" contains "پارکینگ", so a naive
    substring test would read every explicit denial as a yes.
    """
    for phrase in negatives:
        if phrase in text:
            return False
    for phrase in positives:
        if phrase in text:
            return True
    return None


def extract_balcony(text: str) -> Optional[bool]:
    return _mentions(text, ("بالکن", "تراس", "بالکون"), ("بدون بالکن", "بدون تراس", "فاقد بالکن"))


def extract_convertible(text: str) -> Optional[bool]:
    return _mentions(
        text,
        ("قابل تبدیل", "قابليت تبديل", "تبدیل میشود", "تبدیل می شود", "تبدیل به رهن", "کم و زیاد میشود"),
        ("غیر قابل تبدیل", "غیرقابل تبدیل", "بدون تبدیل"),
    )


# --------------------------------------------------------------------------
# other_features / attributes -> typed groups
# --------------------------------------------------------------------------

# Divar ships these as one flat list of sentences ("سرمایش کولر آبی"). Grouping
# them by their leading noun turns the list into filterable facets.
_FEATURE_GROUPS: dict[str, str] = {
    "جنس کف": "floor_material",
    "سرمایش": "cooling",
    "گرمایش": "heating",
    "تأمین‌کننده آب گرم": "water_heater",
    "تامین کننده آب گرم": "water_heater",
    "سرویس بهداشتی": "wc_type",
}


def group_features(raw_features: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for feature in raw_features:
        for prefix, group in _FEATURE_GROUPS.items():
            if feature.startswith(prefix):
                value = feature[len(prefix) :].strip()
                if value:
                    grouped[group].append(value)
                break
    return dict(grouped)


_YES = {"بله", "هست", "دارد", "دارای"}
_PET_VALUES = {"بله": "allowed", "خیر": "not_allowed", "با توافق": "negotiable"}


def _attr_int(attributes: dict[str, str], key: str) -> Optional[int]:
    raw = _norm(attributes.get(key, ""))
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else None


# --------------------------------------------------------------------------
# Neighborhood linking
# --------------------------------------------------------------------------


def _nearest_polygon_key(lat: float, lon: float) -> Optional[str]:
    """The closest polygon by representative point. Only a fallback: the 258
    polygons cover about two thirds of the city, so a listing on a highway or
    in an outlying development legitimately sits inside none of them and still
    has to be reachable from a neighborhood filter."""
    if not nb.NEIGHBORHOODS:
        return None
    return min(
        nb.NEIGHBORHOODS,
        key=lambda n: math.hypot(n.center_lat - lat, n.center_lon - lon),
    ).key


def build_neighborhood_index(raw: list[dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Decide, once for the whole corpus, which of our polygons each Divar
    neighborhood name belongs to.

    Divar recognises 341 neighborhoods where we hold 258 polygons, so a third
    of its names have no polygon of their own. Rather than guess from the name,
    this votes with geometry: every listing that carries an exact point is
    tested against the polygons, and each Divar name is assigned to whichever
    polygon most of its listings physically landed in. A name that never lands
    anywhere falls back to fuzzy title/keyword resolution.

    Returns ``(divar_name -> polygon key, polygon key -> new alias names)``.
    The aliases are the whole reason this is worth doing: folding "شهرک
    مروارید" into the keyword list of the polygon that contains it means a user
    typing Divar's name still finds the right area on our map.
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    for row in raw:
        lat, lon = row.get("lat"), row.get("lon")
        name = (row.get("neighborhood") or "").strip()
        if not name or lat is None or lon is None:
            continue
        match = nb.find_neighborhood(lat, lon)
        if match is not None:
            votes[name][match.key] += 1

    canonical: dict[str, str] = {}
    for name in {(row.get("neighborhood") or "").strip() for row in raw} - {""}:
        if votes[name]:
            canonical[name] = votes[name].most_common(1)[0][0]
            continue
        resolved = nb.resolve_name(name)
        if resolved is not None:
            canonical[name] = resolved
            continue
        # No geometry and no name match: place it at the centroid of the
        # listings that carry it, if any of them have coordinates at all.
        points = [(r["lat"], r["lon"]) for r in raw if (r.get("neighborhood") or "").strip() == name and r.get("lat")]
        if points:
            key = _nearest_polygon_key(
                sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
            )
            if key:
                canonical[name] = key

    # Every alias this run finds is unioned with the ones already on disk.
    # Without that the file erases itself on the second run: neighborhoods.py
    # merges the written aliases into each polygon's keyword list at load time,
    # so by the time we re-run, the names we discovered last time are already
    # "known" and would be found as nothing new to write.
    aliases: dict[str, list[str]] = defaultdict(list, {
        key: list(names) for key, names in _load_existing_aliases().items()
    })
    for name, key in canonical.items():
        neighborhood = nb.get(key)
        if neighborhood is None:
            continue
        known = {nb._squash(neighborhood.title), *map(nb._squash, neighborhood.keywords)}
        if nb._squash(name) not in known:
            aliases[key].append(name)
    return canonical, {key: sorted(set(names)) for key, names in aliases.items() if names}


def _load_existing_aliases() -> dict[str, list[str]]:
    """Aliases written by a previous run, or {} on a first pass."""
    if not ALIASES_PATH.exists():
        return {}
    payload = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    return {str(key): list(names) for key, names in payload.get("aliases", {}).items()}


# --------------------------------------------------------------------------
# Per-listing enrichment
# --------------------------------------------------------------------------


def _clamp_to_tehran(lat: float, lon: float) -> tuple[float, float]:
    return (
        min(max(lat, TEHRAN_BBOX.min_lat), TEHRAN_BBOX.max_lat),
        min(max(lon, TEHRAN_BBOX.min_lon), TEHRAN_BBOX.max_lon),
    )


# "آخرین نردبان" is the timestamp of the advertiser's last paid bump on the
# source marketplace. It says nothing about the property and everything about
# how the advert was promoted there, so it is dropped rather than carried into
# our own listing page. Publication and last-updated dates are kept: those
# tell a renter how stale the offer is.
_PROMOTION_LINE = re.compile(r"^\s*آخرین\s*نردبان.*$", re.MULTILINE)


def _clean_published_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = "\n".join(line for line in _PROMOTION_LINE.sub("", text).splitlines() if line.strip())
    return cleaned or None


# Adverts a human has looked at and judged not to be an offering at all. The
# crawl cannot tell these apart: they are posted in the rental category, with a
# price and a location, but the text is someone *asking* for a home rather than
# renting one out. Rare enough to name individually, and named here so a
# rebuild from the raw crawl keeps dropping them.
_REJECTED_TOKENS: frozenset[str] = frozenset({
    "gaROvms1",  # "به دنبال یک واحد مرتب برای زندگی و دفتر کار" -- a wanted-ad.
})


def process_listing(row: dict, canonical: dict[str, str], dropped: Optional[Counter] = None) -> Optional[dict]:
    """One raw crawl row -> one enriched record. None if it is unusable.

    `dropped`, when given, is a Counter that records *why* each rejected row
    was rejected -- the difference between "the crawl brought back 92 rows we
    could not use" and "92 adverts were withholding their price" is the whole
    value of the summary this feeds.
    """
    def reject(reason: str) -> None:
        if dropped is not None:
            dropped[reason] += 1

    token = row.get("token")
    if not token:
        reject("no_token")
        return None
    if token in _REJECTED_TOKENS:
        reject("manually_rejected")
        return None

    text = _norm(f"{row.get('title', '')}\n{row.get('description', '')}")
    attributes: dict[str, str] = {k: str(v) for k, v in (row.get("attributes") or {}).items()}
    provenance: dict[str, str] = {}
    flags: list[str] = []

    def take(field: str, structured: Any, miner=None, source: str = "divar_attribute") -> Any:
        """Structured value if Divar has one, otherwise whatever the ad text
        yields -- recording which of the two answered."""
        if structured is not None:
            provenance[field] = source
            return structured
        if miner is not None:
            mined = miner()
            if mined is not None:
                provenance[field] = "listing_text"
                return mined
        provenance[field] = "unknown"
        return None

    # --- money -------------------------------------------------------------
    deposit = int(row.get("deposit_toman") or 0)
    rent = int(row.get("rent_toman") or 0)
    provenance["deposit_toman"] = provenance["rent_toman"] = "divar_structured"
    # Divar states "غیر قابل تبدیل" explicitly; anything else is only knowable
    # from the ad copy, where "قابل تبدیل" is near-universal boilerplate.
    convert_attr = attributes.get("ودیعه و اجاره")
    can_convert = take(
        "can_convert",
        False if convert_attr and "غیر" in convert_attr else (True if convert_attr else None),
        lambda: extract_convertible(text),
    )
    if can_convert is None:
        can_convert = bool(row.get("can_convert"))
        provenance["can_convert"] = "default"

    # --- size and shape ----------------------------------------------------
    area = row.get("area_sqm")
    if area is None or not (_MIN_PLAUSIBLE_AREA <= area <= _MAX_PLAUSIBLE_AREA):
        mined = extract_area(text)
        if mined is not None:
            flags.append("area_repaired_from_text")
            area, provenance["area_sqm"] = mined, "listing_text"
        elif area is None:
            reject("no_area")
            return None
        else:
            flags.append("area_implausible")
            area = min(max(int(area), _MIN_PLAUSIBLE_AREA), _MAX_PLAUSIBLE_AREA)
            provenance["area_sqm"] = "divar_structured_clamped"
    else:
        provenance["area_sqm"] = "divar_structured"

    # An advert priced at a token ۱٬۰۰۰ تومان is asking the reader to phone for
    # the real figure. Dropped rather than flagged: a placeholder price beats
    # every genuine listing on the budget criterion, so anything short of
    # removal puts it at the top of the results. See price_plausibility.py.
    #
    # Tested here rather than beside the money block above because the
    # per-square-metre floor needs the *resolved* area -- the one that goes
    # into the database. Judging it on the raw figure would let an advert
    # through this stage and then have database.purge_placeholder_prices
    # delete it later, which is the same rule disagreeing with itself.
    if is_placeholder_price(deposit, rent, area):
        reject("placeholder_price")
        return None

    rooms = take("rooms", row.get("rooms"), lambda: extract_rooms(text), source="divar_structured")
    if rooms is None:
        # An apartment with no stated bedroom count is far more often a studio
        # advertised loosely than a five-bed penthouse, but guessing zero would
        # break the "at least N rooms" filter. Estimate from area instead and
        # say so.
        rooms, provenance["rooms"] = min(5, max(1, round(area / 40))), "estimated_from_area"
    rooms = min(10, max(0, int(rooms)))

    attr_floor, attr_total = extract_floor_pair(attributes.get("طبقه", ""))
    floor = take("floor", row.get("floor") if row.get("floor") is not None else attr_floor)
    if floor is None:
        floor, provenance["floor"] = 0, "default"
    floor = min(40, max(-2, int(floor)))

    total_floors = take(
        "total_floors",
        row.get("total_floors") or attr_total or _attr_int(attributes, "تعداد کل طبقات ساختمان"),
        lambda: extract_total_floors(text),
    )
    if total_floors is None or total_floors < floor:
        total_floors, provenance["total_floors"] = max(floor, 1), "derived_from_floor"
    total_floors = min(40, int(total_floors))

    build_year = row.get("build_year")
    provenance["build_year"] = (
        "divar_structured_upper_bound" if row.get("build_year_is_upper_bound") else "divar_structured"
    ) if build_year else "unknown"

    for field in ("has_elevator", "has_parking", "has_storage"):
        provenance[field] = "divar_structured"
    has_balcony = take("has_balcony", row.get("has_balcony"), lambda: extract_balcony(text), source="divar_structured")

    # --- location ----------------------------------------------------------
    divar_name = (row.get("neighborhood") or "").strip()
    key = None
    lat, lon = row.get("lat"), row.get("lon")
    link_method = "none"
    if lat is not None and lon is not None:
        lat, lon = _clamp_to_tehran(float(lat), float(lon))
        match = nb.find_neighborhood(lat, lon)
        if match is not None:
            key, link_method = match.key, "point_in_polygon"
        else:
            key = canonical.get(divar_name) or _nearest_polygon_key(lat, lon)
            link_method = "divar_name_vote" if canonical.get(divar_name) else "nearest_polygon"
        provenance["lat"] = provenance["lon"] = "divar_structured"
    else:
        # 58 rows have no point at all. Anchoring them on the polygon their
        # Divar neighborhood name maps to keeps them searchable and honest --
        # the precision field says the coordinate is a neighborhood, not a door.
        key = canonical.get(divar_name) or nb.resolve_name(divar_name)
        link_method = "neighborhood_centroid"
        neighborhood = nb.get(key) if key else None
        if neighborhood is None:
            reject("no_location")
            return None
        lat, lon = neighborhood.center_lat, neighborhood.center_lon
        provenance["lat"] = provenance["lon"] = "neighborhood_centroid"
        flags.append("position_is_neighborhood_centroid")

    neighborhood = nb.get(key) if key else None
    precision = row.get("location_precision") or ("NEIGHBORHOOD" if link_method == "neighborhood_centroid" else None)
    radius = row.get("location_radius_meters")

    station, dist_km, walk_mins = find_nearest_metro_station(lat, lon)
    district = find_district(lat, lon)

    raw_features = list(row.get("other_features") or [])
    images = list(row.get("images") or [])

    return {
        "id": f"divar-{token}",
        # --- what the ad says, verbatim ------------------------------------
        "title": (row.get("title") or "").strip(),
        "description": (row.get("description") or "").strip(),
        # --- reliable, typed ------------------------------------------------
        "facts": {
            "deposit_toman": deposit,
            "rent_toman": rent,
            "effective_monthly_cost": calculate_effective_monthly_cost(deposit, rent),
            "can_convert": bool(can_convert),
            "convertible_deposit_max_toman": row.get("convertible_deposit_max_toman"),
            "is_full_rahn": bool(row.get("is_full_rahn")),
            "area_sqm": int(area),
            "rooms": rooms,
            "floor": floor,
            "total_floors": total_floors,
            "build_year": build_year,
            "building_age_years": max(0, CURRENT_JALALI_YEAR - build_year) if build_year else None,
            "has_elevator": bool(row.get("has_elevator")),
            "has_parking": bool(row.get("has_parking")),
            "has_storage": bool(row.get("has_storage")),
            "has_balcony": bool(has_balcony) if has_balcony is not None else False,
            "units_per_floor": _attr_int(attributes, "تعداد واحد در طبقه"),
            "min_contract_months": _attr_int(attributes, "حداقل مدت قرارداد"),
            "direction": attributes.get("جهت ساختمان"),
            "kitchen_type": attributes.get("نوع آشپزخانه"),
            "is_renovated": attributes.get("بازسازی‌ شده") in _YES,
            "is_furnished": attributes.get("مبله") in _YES,
            "has_pool": attributes.get("استخر") in _YES,
            "has_sauna": attributes.get("سونا") in _YES,
            "has_jacuzzi": attributes.get("جکوزی") in _YES,
            "pets_policy": _PET_VALUES.get((attributes.get("حیوان خانگی مجاز") or "").strip()),
        },
        # --- Divar's own مشخصات table, kept whole for the detail page -------
        "attributes": attributes,
        "features": group_features(raw_features),
        "raw_features": raw_features,
        "suitable_for": list(row.get("suitable_for") or []),
        # --- where -----------------------------------------------------------
        "location": {
            "lat": lat,
            "lon": lon,
            "h3_index": h3.latlng_to_cell(lat, lon, H3_RESOLUTION),
            "precision": precision,
            "radius_meters": radius,
            "divar_neighborhood": divar_name,
            "divar_slug": row.get("neighborhood_slug"),
            "neighborhood_key": key,
            "neighborhood_title": neighborhood.title if neighborhood else divar_name,
            "link_method": link_method,
            "district": district,
            "city": row.get("city") or "تهران",
            "nearest_metro_id": station["id"],
            "nearest_metro_name": station["name"],
            "dist_to_metro_meters": dist_km * 1000,
            "metro_walk_mins": walk_mins,
            "in_tarh_terafik": is_inside_tarh_terafik(lat, lon),
            "in_tarh_aloodegi": is_inside_tarh_aloodegi(lat, lon),
        },
        "media": {
            "image_count": int(row.get("image_count") or len(images)),
            "images": images,
            # Divar asks the advertiser to confirm the photos are of this unit;
            # a "خیر" is a real signal and the detail page shows it.
            "images_are_authentic": attributes.get("تصویر‌ها برای همین ملک است؟") == "بله",
        },
        "source": {
            "platform": "divar",
            "token": token,
            "url": row.get("url"),
            "business_type": row.get("business_type"),
            "published_text": _clean_published_text(row.get("published_text")),
            "unavailable_after": row.get("unavailable_after"),
            "crawled_at": row.get("crawled_at"),
        },
        "provenance": provenance,
        "quality_flags": flags,
    }


def to_listing(record: dict) -> Listing:
    """Enriched record -> the domain model the ranking engine consumes."""
    facts, location, media, source = record["facts"], record["location"], record["media"], record["source"]
    return Listing(
        id=record["id"],
        title=record["title"] or f"{to_persian_digits(facts['area_sqm'])} متر، {location['neighborhood_title']}",
        description=record["description"],
        neighborhood=location["neighborhood_title"],
        neighborhood_key=location["neighborhood_key"],
        district=to_persian_digits(location["district"]) if location.get("district") else None,
        deposit_toman=facts["deposit_toman"],
        rent_toman=facts["rent_toman"],
        effective_monthly_cost=facts["effective_monthly_cost"],
        can_convert=facts["can_convert"],
        convertible_deposit_max_toman=facts["convertible_deposit_max_toman"],
        is_full_rahn=facts["is_full_rahn"],
        # Read off the advertiser's own words; there is no field on the
        # advert that says "this is a room, or a parking space, not a flat".
        is_shared_living=is_not_a_home(record["title"], record["description"]),
        area_sqm=facts["area_sqm"],
        rooms=facts["rooms"],
        floor=facts["floor"],
        total_floors=facts["total_floors"],
        has_elevator=facts["has_elevator"],
        has_parking=facts["has_parking"],
        has_balcony=facts["has_balcony"],
        has_storage=facts["has_storage"],
        building_age_years=facts["building_age_years"] if facts["building_age_years"] is not None else 5,
        build_year=facts["build_year"],
        lat=location["lat"],
        lon=location["lon"],
        h3_index=location["h3_index"],
        nearest_metro_id=location["nearest_metro_id"],
        nearest_metro_name=location["nearest_metro_name"],
        dist_to_metro_meters=location["dist_to_metro_meters"],
        metro_walk_mins=location["metro_walk_mins"],
        in_tarh_terafik=location["in_tarh_terafik"],
        in_tarh_aloodegi=location["in_tarh_aloodegi"],
        source="divar",
        source_url=source.get("url"),
        image_count=media["image_count"],
        images=media["images"],
        location_precision=location.get("precision"),
        location_radius_meters=location.get("radius_meters"),
        images_are_authentic=media["images_are_authentic"],
        units_per_floor=facts["units_per_floor"],
        min_contract_months=facts["min_contract_months"],
        direction=facts["direction"],
        kitchen_type=facts["kitchen_type"],
        is_renovated=facts["is_renovated"],
        is_furnished=facts["is_furnished"],
        has_pool=facts["has_pool"],
        has_sauna=facts["has_sauna"],
        has_jacuzzi=facts["has_jacuzzi"],
        pets_policy=facts["pets_policy"],
        features=record["features"],
        suitable_for=record["suitable_for"],
        attributes=record["attributes"],
        provenance=record["provenance"],
        published_text=source.get("published_text"),
        created_at=source.get("crawled_at") or datetime.now(timezone.utc).isoformat(),
    )


def _drop_local_price_outliers(records: list[dict], dropped: Counter) -> list[dict]:
    """Second placeholder pass: too cheap *for where it stands*.

    The per-record test above knows only absolute floors, and a placeholder
    priced like an ordinary flat in a district where nothing is ordinary
    walks straight past it. This one needs the whole corpus at once -- it
    compares each home with the ones within about a kilometre of it -- so it
    can only run here, after every record has been resolved. The measured
    floors are written to disk so the crawler applies the same judgement to
    new adverts instead of letting them in to be cleaned up later. See
    app/data/price_plausibility.py.
    """
    samples = [
        (
            record["location"]["lat"],
            record["location"]["lon"],
            record["facts"]["effective_monthly_cost"] / record["facts"]["area_sqm"],
        )
        for record in records
        if record["facts"]["area_sqm"]
    ]
    floors = local_price_floors(samples)
    save_price_floors(floors)

    kept = []
    for record in records:
        if is_local_price_outlier(
            floors,
            record["location"]["lat"],
            record["location"]["lon"],
            record["facts"]["deposit_toman"],
            record["facts"]["rent_toman"],
            record["facts"]["area_sqm"],
        ):
            dropped["local_price_outlier"] += 1
            continue
        kept.append(record)
    return kept


def run(raw_path: Path = RAW_CRAWL_PATH, out_path: Path = PROCESSED_PATH) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    canonical, aliases = build_neighborhood_index(raw)

    dropped: Counter = Counter()
    records = [record for record in (process_listing(row, canonical, dropped) for row in raw) if record is not None]
    records = _drop_local_price_outliers(records, dropped)

    out_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    ALIASES_PATH.write_text(
        json.dumps(
            {
                "generated_from": raw_path.name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "aliases": aliases,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    provenance_counts: Counter = Counter()
    for record in records:
        for field, origin in record["provenance"].items():
            provenance_counts[f"{field}:{origin}"] += 1
    return {
        "raw": len(raw),
        "processed": len(records),
        "dropped": len(raw) - len(records),
        "dropped_reasons": dict(dropped),
        "divar_neighborhoods": len(canonical),
        "aliased_polygons": len(aliases),
        "new_aliases": sum(len(v) for v in aliases.values()),
        "text_derived": {k: v for k, v in provenance_counts.items() if k.endswith("listing_text")},
        "unknown": {k: v for k, v in provenance_counts.items() if k.endswith(":unknown")},
        "flags": Counter(flag for record in records for flag in record["quality_flags"]),
    }


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
