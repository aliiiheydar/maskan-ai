"""Fill the holes in Tehran's neighborhood map.

``matched_neighborhoods.geojson`` carries the 258 محله that a curated polygon
and a listings-portal key could both be found for. That leaves about a third
of the city inside no neighborhood at all: a click there resolves to nothing,
those listings can only be found by drawing a box, and a search for the area's
own name finds nothing. Most of that hole is not unmapped -- 107 named
polygons in ``tehran_neighborhoods.geojson`` simply never matched a key, and
they account for 193 of the 204 uncovered square kilometres.

This script turns those into first-class neighborhoods, and names them from
map data:

  1. **Polygons.** The unmatched curated polygons, plus whatever sizeable land
     is *still* outside everything afterwards, cut into pieces big enough to
     be a neighborhood in their own right (see ``MIN_AREA_SQKM``, set from the
     smallest existing محله) and thick enough not to be a road corridor.
  2. **Names and keywords, from OpenStreetMap.** A curated polygon carries a
     name and nothing else, and four of them are literally named "Unknown".
     What makes neighborhood search work is not the title but the streets and
     landmarks people name when they mean the place -- "سئول، فجر، ونک" for
     آرارات. So each polygon is handed to Overpass as a `poly:` filter and the
     named streets, transit stops, parks and civic landmarks *inside it* come
     back to become its ``search_keywords``, in the same comma-separated shape
     the portal's own subtitles use.

Nothing here is written back to a source: the curated KML, the matched
polygons and the pairing files are read-only inputs, and the whole result
lands in ``gap_neighborhoods.geojson``, which ``app.spatial.neighborhoods``
merges in alongside them. Overpass answers are cached in
``osm_area_context.json`` so a re-run costs no requests.

    python -m app.data.build_gap_neighborhoods            # build, using the cache
    python -m app.data.build_gap_neighborhoods --refresh  # re-query Overpass
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.normalizers import normalize_persian_text  # noqa: E402
from app.spatial.districts import find_district  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent
KML_PATH = _DATA_DIR / "tehran_neighborhoods.geojson"
MATCHED_PATH = _DATA_DIR / "matched_neighborhoods.geojson"
UNMATCHED_PATH = _DATA_DIR / "unmatched_neighborhoods.json"
CITY_PATH = _DATA_DIR / "tehran.geojson"
OUTPUT_PATH = _DATA_DIR / "gap_neighborhoods.geojson"
CACHE_PATH = _DATA_DIR / "osm_area_context.json"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# The smallest existing محله is 0.17 km2, so anything above 0.15 is "big
# enough to be a neighborhood" by the corpus's own standard.
MIN_AREA_SQKM = 0.15
# Leftover land has to survive a 200 m erosion to count: the gap between two
# neighborhoods is usually a boulevard, and a 6-lane highway is not a place to
# live no matter how many square metres of it there are.
MIN_THICKNESS_M = 200
# Two polygons this close under the same name are one place the source split
# in two; further apart they are two different places that share a name.
MERGE_DISTANCE_M = 60

# The curated KML leaves four polygons unnamed. They are real land, so they
# are kept and named from OpenStreetMap like any other piece.
UNNAMED = {"unknown", "", "نامشخص"}

_LAT0, _LON0 = 35.70, 51.35
_M_PER_DEG = 111320.0


def _to_m(lon: float, lat: float) -> tuple[float, float]:
    return ((lon - _LON0) * _M_PER_DEG * math.cos(math.radians(_LAT0)), (lat - _LAT0) * _M_PER_DEG)


def _to_deg(x: float, y: float) -> tuple[float, float]:
    return (x / (_M_PER_DEG * math.cos(math.radians(_LAT0))) + _LON0, y / _M_PER_DEG + _LAT0)


def _sqkm(geometry: BaseGeometry) -> float:
    return transform(_to_m, geometry).area / 1e6


_ZWNJ = re.compile(r"[​-‏]")
_DIACRITICS = re.compile(r"[ً-ْ]")


def _norm(text: str) -> str:
    cleaned = _ZWNJ.sub(" ", _DIACRITICS.sub("", text or ""))
    return re.sub(r"\s+", " ", normalize_persian_text(cleaned)).strip()


def _squash(text: str) -> str:
    return _norm(text).replace(" ", "")


# A keyword is the name people say, not the road classification in front of
# it: nobody searches for "بزرگراه شهید همت", they search for "همت".
_GENERIC_PREFIX = re.compile(
    r"^(بزرگراه|اتوبان|آزادراه|خیابان|خ\.|بلوار|بلوار شهید|میدان|میدان شهید|کوچه|پل|تقاطع|فلکه|شهید)\s+"
)
_PERSIAN = re.compile(r"[؀-ۿ]")

# Municipal bookkeeping labels. "ناحیه ۵" is on the map and inside the
# polygon, but nobody has ever looked for a flat in ناحیه ۵ -- as a keyword it
# only creates collisions between the dozens of areas that contain one.
_ADMIN_LABEL = re.compile(r"^(منطقه|ناحیه|زون)\s*[۰-۹0-9]")

# A landmark is worth listing as a keyword and useless as a title: an area
# called "بوستان فرهنگیان" or "پاساژ آبان" reads as a park or a shop, and a
# renter scanning the picker would not recognise it as the place they live.
_LANDMARK_TITLE = re.compile(
    r"^(بوستان|پارک|پاساژ|مرکز خرید|مجتمع تجاری|بازار|بیمارستان|درمانگاه|دانشگاه|دانشکده"
    r"|ورزشگاه|استادیوم|فرودگاه|ایستگاه|مترو|مصلی|مسجد|امامزاده|برج|هتل|موزه|فرهنگسرا)\b"
)


def _clean_name(name: str) -> Optional[str]:
    """A map label reduced to the phrase a person would type, or None if it is
    not usable as one."""
    cleaned = _norm(name)
    while True:
        stripped = _GENERIC_PREFIX.sub("", cleaned).strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    # Latin-only labels are OSM's English duplicates; a Persian search box
    # will never match them, so they are noise in the keyword list.
    if not cleaned or not _PERSIAN.search(cleaned) or len(cleaned) < 3:
        return None
    if _ADMIN_LABEL.match(cleaned):
        return None
    return cleaned


def _load_features(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def _geometry(feature: dict) -> BaseGeometry:
    geometry = shape(feature["geometry"])
    return geometry if geometry.is_valid else geometry.buffer(0)


def _city_boundary() -> BaseGeometry:
    polygons = [
        _geometry(feature)
        for feature in _load_features(CITY_PATH)
        if feature.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")
    ]
    return max(polygons, key=lambda p: p.area)


class Candidate:
    """One area that is going to become a neighborhood."""

    def __init__(self, geometry: BaseGeometry, title: Optional[str], source: str) -> None:
        self.geometry = geometry
        self.title = title
        self.source = source
        self.key = ""
        self.subtitle = ""
        self.keywords: list[str] = []
        self.context: dict[str, list[str]] = {}
        anchor = geometry.representative_point()
        self.lat, self.lon = anchor.y, anchor.x
        self.district = find_district(self.lat, self.lon)
        self.area_sqkm = _sqkm(geometry)


def _curated_candidates() -> list[Candidate]:
    """The named polygons the matcher could not pair with a key.

    Same-name polygons that sit next to each other are one place the source
    split along a street and are merged; same-name polygons on opposite sides
    of the city (کوهسار appears twice, 15 km apart) are two real places and
    stay separate -- they are told apart by their district further down.
    """
    used = {feature["properties"].get("kml_name") for feature in _load_features(MATCHED_PATH)}
    by_name: dict[str, list[BaseGeometry]] = defaultdict(list)
    for feature in _load_features(KML_PATH):
        name = feature["properties"].get("name") or ""
        if name in used:
            continue
        by_name[name].append(_geometry(feature))

    candidates: list[Candidate] = []
    for name, polygons in by_name.items():
        clusters: list[list[BaseGeometry]] = []
        for polygon in polygons:
            metric = transform(_to_m, polygon)
            for cluster in clusters:
                if any(transform(_to_m, other).distance(metric) <= MERGE_DISTANCE_M for other in cluster):
                    cluster.append(polygon)
                    break
            else:
                clusters.append([polygon])
        for cluster in clusters:
            merged = unary_union(cluster) if len(cluster) > 1 else cluster[0]
            if _sqkm(merged) < MIN_AREA_SQKM:
                continue
            title = None if _squash(name).lower() in UNNAMED else _norm(name)
            candidates.append(Candidate(merged, title, "curated-polygon"))
    return candidates


def _leftover_candidates(covered: BaseGeometry) -> list[Candidate]:
    """Land still inside no neighborhood once the curated polygons are in.

    The 30 m buffer on the covered area is what keeps the street *between* two
    neighborhoods from being reported as a hole in the map.
    """
    city_m = transform(_to_m, _city_boundary())
    remainder = city_m.difference(transform(_to_m, covered).buffer(30))
    pieces = remainder.geoms if remainder.geom_type == "MultiPolygon" else [remainder]

    candidates: list[Candidate] = []
    for piece in pieces:
        if piece.area / 1e6 < MIN_AREA_SQKM or piece.buffer(-MIN_THICKNESS_M).is_empty:
            continue
        # Opening the shape sands off the ragged one-pixel fringe left by
        # subtracting a hundred polygons, without moving the real edges.
        cleaned = piece.buffer(-40).buffer(40)
        if cleaned.is_empty:
            continue
        if cleaned.geom_type == "MultiPolygon":
            cleaned = max(cleaned.geoms, key=lambda g: g.area)
        candidates.append(Candidate(transform(_to_deg, cleaned), None, "uncovered-land"))
    return candidates


# What counts as a landmark worth remembering about an area, in the order the
# keywords are listed: the names locals use for the place itself, then the
# roads that bound it, then what is on it.
_OVERPASS_QUERY = """[out:json][timeout:90];
(
  node["place"~"^(suburb|neighbourhood|quarter|locality)$"]["name"](poly:"{poly}");
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]["name"](poly:"{poly}");
  node["railway"="station"]["name"](poly:"{poly}");
  node["public_transport"="station"]["name"](poly:"{poly}");
  way["leisure"="park"]["name"](poly:"{poly}");
  way["amenity"~"^(university|college|hospital|marketplace)$"]["name"](poly:"{poly}");
  node["amenity"~"^(university|college|hospital|marketplace)$"]["name"](poly:"{poly}");
  way["shop"="mall"]["name"](poly:"{poly}");
  node["shop"="mall"]["name"](poly:"{poly}");
);
out tags center;"""


def _poly_filter(geometry: BaseGeometry) -> str:
    """The polygon as Overpass wants it: "lat lon lat lon ...", simplified,
    because the filter is sent in a URL-encoded body and a 3,000-point ring
    would be rejected long before it was useful."""
    outline = geometry if geometry.geom_type == "Polygon" else max(geometry.geoms, key=lambda g: g.area)
    ring = outline.exterior
    for tolerance in (0.0, 0.0002, 0.0005, 0.001, 0.002):
        simplified = ring.simplify(tolerance) if tolerance else ring
        coords = list(simplified.coords)
        if len(coords) <= 60:
            break
    return " ".join(f"{lat:.5f} {lon:.5f}" for lon, lat in coords[:-1])


def _classify(element: dict) -> Optional[str]:
    tags = element.get("tags", {})
    if tags.get("place"):
        return "places"
    if tags.get("highway"):
        return "roads"
    if tags.get("railway") == "station" or tags.get("public_transport") == "station":
        return "transit"
    return "landmarks"


def _query_overpass(client: httpx.Client, geometry: BaseGeometry) -> dict[str, list[str]]:
    query = _OVERPASS_QUERY.format(poly=_poly_filter(geometry))
    for attempt in range(4):
        try:
            response = client.post(OVERPASS_URL, data={"data": query})
            if response.status_code in (429, 504):
                time.sleep(8 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            break
        except Exception as error:  # noqa: BLE001 -- a slow shard is not fatal
            if attempt == 3:
                print(f"  overpass failed: {error}", file=sys.stderr)
                return {}
            time.sleep(8 * (attempt + 1))
    else:
        return {}

    buckets: dict[str, list[str]] = defaultdict(list)
    for element in payload.get("elements", []):
        bucket = _classify(element)
        name = _clean_name(element.get("tags", {}).get("name", ""))
        if bucket and name and name not in buckets[bucket]:
            buckets[bucket].append(name)
    return dict(buckets)


def _sanitize(context: dict[str, list[str]]) -> dict[str, list[str]]:
    """Re-apply the name rules to a cached answer.

    The cache holds what the rules accepted on the day it was written, so a
    rule added afterwards has to be applied on the way out as well -- or a
    rebuild would keep every name the old rules let through and the cache
    would have to be thrown away to fix a typo in a regex.
    """
    cleaned: dict[str, list[str]] = {}
    for bucket, names in context.items():
        kept = [name for name in (_clean_name(name) for name in names) if name]
        if kept:
            cleaned[bucket] = kept
    return cleaned


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8")).get("areas", {})


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.write_text(
        json.dumps(
            {
                "source": "OpenStreetMap via Overpass API (ODbL)",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "areas": cache,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def _cache_id(candidate: Candidate) -> str:
    digest = hashlib.sha1(f"{candidate.lat:.5f},{candidate.lon:.5f}".encode()).hexdigest()
    return digest[:10]


def _stable_key(candidate: Candidate) -> str:
    """A key that survives a rebuild.

    Keys are stored on listings and held in the client's selection, so they
    cannot be positional. The anchor point is derived from the geometry, so
    the same polygon yields the same key every time.
    """
    return "g" + hashlib.sha1(f"{candidate.title}|{candidate.lat:.4f},{candidate.lon:.4f}".encode()).hexdigest()[:7]


def _name_from_osm(context: dict[str, list[str]]) -> Optional[str]:
    """A title for a piece of land the curated map never named.

    Only a `place` label will do -- a name someone put on the map to mean
    "this area". Naming the area after the park or the mall inside it would
    invent a neighborhood that no one calls by that name, so a piece with no
    place label is left out of the map entirely.
    """
    for name in context.get("places", []):
        if not _LANDMARK_TITLE.match(name):
            return name
    return None


def _keywords(candidate: Candidate, context: dict[str, list[str]]) -> list[str]:
    """The phrases that should find this area, best signal first.

    Roads are capped because a large polygon can contain thirty named streets,
    and a keyword list that long stops discriminating between neighborhoods --
    it starts matching all of them.
    """
    ordered: list[str] = []
    for name in context.get("places", [])[:4]:
        ordered.append(name)
    for name in context.get("roads", [])[:6]:
        ordered.append(name)
    for name in context.get("transit", [])[:3]:
        ordered.append(name)
    for name in context.get("landmarks", [])[:3]:
        ordered.append(name)

    seen: set[str] = set()
    unique: list[str] = []
    for name in ordered:
        squashed = _squash(name)
        if squashed and squashed not in seen and squashed != _squash(candidate.title or ""):
            seen.add(squashed)
            unique.append(name)
    return unique


def _portal_pairs() -> dict[str, dict]:
    """Portal neighborhoods that have a name but no polygon, by squashed title.

    Only an exact title match is honoured. A near match ("تهرانپارس" onto
    "تهرانپارس جنوبی") would hand one area's key -- and with it every listing
    that names it -- to the polygon next door, and these keys have no polygon
    today precisely because nobody could confirm where they are.
    """
    payload = json.loads(UNMATCHED_PATH.read_text(encoding="utf-8"))
    pairs: dict[str, dict] = {}
    for child in payload.get("children", []):
        data = child["data"]
        pairs.setdefault(_squash(data["title"]), data)
    return pairs


def run(refresh: bool = False) -> dict:
    curated = _curated_candidates()
    matched_geoms = [_geometry(feature) for feature in _load_features(MATCHED_PATH)]
    covered = unary_union(matched_geoms + [c.geometry for c in curated])
    leftover = _leftover_candidates(covered)
    candidates = curated + leftover
    print(f"{len(curated)} curated polygons + {len(leftover)} uncovered pieces", flush=True)

    cache = _load_cache()
    client = httpx.Client(
        timeout=120.0,
        headers={"User-Agent": "maskan-ai/0.1 (neighborhood coverage)"},
        # This machine exports ALL_PROXY for a VPN; Overpass must not be
        # reached through it, for the same reason the crawler bypasses it.
        trust_env=False,
    )
    try:
        for index, candidate in enumerate(candidates, start=1):
            cache_id = _cache_id(candidate)
            if refresh or cache_id not in cache:
                cache[cache_id] = _query_overpass(client, candidate.geometry)
                _save_cache(cache)
                time.sleep(1.5)
                print(f"  [{index}/{len(candidates)}] {candidate.title or '(unnamed)'}: "
                      f"{sum(len(v) for v in cache[cache_id].values())} map features", flush=True)
            candidate.context = _sanitize(cache[cache_id])
    finally:
        client.close()

    portal = _portal_pairs()
    named: list[Candidate] = []
    for candidate in candidates:
        context = candidate.context
        if not candidate.title:
            candidate.title = _name_from_osm(context)
        if not candidate.title:
            # An unnamed piece of land with nothing named on it either is not
            # a neighborhood anyone could search for; better a hole in the map
            # than an invented place name.
            continue
        candidate.keywords = _keywords(candidate, context)
        named.append(candidate)

    # Two areas that genuinely share a name are told apart by their district,
    # so neither the picker nor name resolution has to guess which is meant.
    counts: dict[str, int] = defaultdict(int)
    for candidate in named:
        counts[_squash(candidate.title or "")] += 1
    for candidate in named:
        base = candidate.title or ""
        if counts[_squash(base)] > 1 and candidate.district:
            candidate.title = f"{base} ({candidate.district})"
        # Someone searching "کوهسار" means one of the two areas called that,
        # and someone searching "دزاشیب" means the half of حکمت-دزاشیب they
        # live in. Both are unreachable by title once the title is qualified
        # or compound, so every plain form of the name becomes a keyword.
        variants = [base] + [part.strip() for part in re.split(r"[-–—/]", base) if part.strip()]
        for variant in variants:
            if _squash(variant) != _squash(candidate.title or "") and variant not in candidate.keywords:
                candidate.keywords.insert(0, variant)

    features = []
    taken_keys: set[str] = set()
    paired = 0
    for candidate in named:
        match = portal.get(_squash(candidate.title or ""))
        if match and match["key"] not in taken_keys:
            candidate.key = match["key"]
            candidate.subtitle = match.get("subtitle", "")
            portal_keywords = [k.strip() for k in re.split(r"[،,؛;]+", match.get("search_keywords", "")) if k.strip()]
            candidate.keywords = list(dict.fromkeys(portal_keywords + candidate.keywords))
            paired += 1
        else:
            candidate.key = _stable_key(candidate)
        taken_keys.add(candidate.key)

        if not candidate.subtitle:
            candidate.subtitle = "، ".join(candidate.keywords[:5])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "key": candidate.key,
                    "title": candidate.title,
                    "subtitle": candidate.subtitle,
                    "search_keywords": "، ".join(candidate.keywords + [candidate.title or ""]),
                    "district": candidate.district,
                    "source": candidate.source,
                    "area_sqkm": round(candidate.area_sqkm, 3),
                },
                "geometry": mapping(candidate.geometry),
            }
        )

    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "app.data.build_gap_neighborhoods",
                "keywords_source": "OpenStreetMap via Overpass API (ODbL)",
                "features": features,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    covered_all = unary_union(matched_geoms + [c.geometry for c in named])
    city = _city_boundary()
    return {
        "curated_polygons": len(curated),
        "uncovered_pieces": len(leftover),
        "written": len(features),
        "dropped_unnamed": len(candidates) - len(named),
        "paired_with_portal_key": paired,
        "area_added_sqkm": round(sum(c.area_sqkm for c in named), 1),
        "city_coverage_before_pct": round(100 * unary_union(matched_geoms).intersection(city).area / city.area, 1),
        "city_coverage_after_pct": round(100 * covered_all.intersection(city).area / city.area, 1),
        "output": str(OUTPUT_PATH.relative_to(_DATA_DIR.parents[1])),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build neighborhoods for the uncovered parts of Tehran.")
    parser.add_argument("--refresh", action="store_true", help="re-query Overpass instead of using the cache")
    print(json.dumps(run(refresh=parser.parse_args().refresh), ensure_ascii=False, indent=2))
