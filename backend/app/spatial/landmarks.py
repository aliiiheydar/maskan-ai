"""A gazetteer of named points in Tehran -- squares, universities, hospitals,
terminals, malls.

Two things in this product are stated as a *place* rather than as a محله: the
workplace ("محل کارم توی دانشگاه شریفه") and the area someone wants to live
around ("محدوده تئاتر شهر و انقلاب"). Neither is a neighborhood name, so the
polygon resolver alone cannot answer them: it can only fall back on the
landmark keywords attached to each محله, which is how "انقلاب" used to land on
بهارستان -- a neighborhood two kilometres away that happens to list an
انقلاب-named street among its keywords.

A point does answer both. The workplace becomes coordinates the commute
estimator and the map pin can use, and the search area becomes "whichever
محله this point falls in, plus the ones a short walk around it".

The station file is the bulk of the gazetteer -- 320 distinct names, and the
squares, universities and terminals Tehranis name are overwhelmingly metro or
BRT stops. ``app/data/landmarks.json`` fills the gaps.
"""

import json
from difflib import SequenceMatcher
from functools import lru_cache
from typing import NamedTuple, Optional

from app.core import paths
from app.core.normalizers import normalize_for_match, squash_for_match

_TRANSIT_PATH = paths.asset("tehran_transit_nodes.json")
_LANDMARKS_PATH = paths.asset("landmarks.json")

# Words that classify a place rather than name it. Stripped so "میدان ونک"
# matches "ونک", and never indexed on their own -- "دانشگاه" alone identifies
# nothing.
_GENERIC = {
    "میدان",
    "میدون",
    "خیابان",
    "خ",
    "بلوار",
    "بزرگراه",
    "اتوبان",
    "کوچه",
    "پل",
    "سه راه",
    "سهراه",
    "چهارراه",
    "چهار راه",
    "مترو",
    "متروی",
    "ایستگاه",
    "پایانه",
    "ترمینال",
    "شهرک",
    "منطقه",
    "محله",
    "محدوده",
    "حوالی",
    "نزدیک",
    "اطراف",
    "دانشگاه",
    "دانشکده",
    "بیمارستان",
    "بوستان",
    "پارک",
    "برج",
    "مجتمع",
    "شرکت",
    "شهید",
    "امام",
    "اسلامی",
}

# Below this, an edit-distance match is a coincidence rather than a typo:
# "ونک" and "بنک" would pass at anything looser.
_FUZZY_THRESHOLD = 0.85
_MIN_FUZZY_LENGTH = 4


class Landmark(NamedTuple):
    name: str
    lat: float
    lon: float
    kind: str  # "metro" | "brt" | "poi"


def _strip_generic(name: str) -> str:
    """The distinguishing part of a place name: "میدان انقلاب اسلامی" -> "انقلاب"."""
    tokens = [token for token in normalize_for_match(name).split(" ") if token and token not in _GENERIC]
    return "".join(tokens)


def _tokens(name: str) -> list[str]:
    return [
        squash_for_match(token)
        for token in normalize_for_match(name).split(" ")
        if token not in _GENERIC and len(token) >= 3
    ]


def _load() -> list[Landmark]:
    """One entry per distinct name, stations first.

    A name shared by a metro station and its BRT stop is one place to the user
    even though the two platforms are 200 m apart, so their coordinates are
    averaged rather than competing.
    """
    grouped: dict[str, list[dict]] = {}
    for node in json.loads(_TRANSIT_PATH.read_text(encoding="utf-8")):
        grouped.setdefault(squash_for_match(node["name"]), []).append(node)

    landmarks: list[Landmark] = []
    for nodes in grouped.values():
        kind = "metro" if any(n.get("type") == "metro" for n in nodes) else "brt"
        landmarks.append(
            Landmark(
                name=nodes[0]["name"],
                lat=sum(n["lat"] for n in nodes) / len(nodes),
                lon=sum(n["lon"] for n in nodes) / len(nodes),
                kind=kind,
            )
        )

    if _LANDMARKS_PATH.exists():
        payload = json.loads(_LANDMARKS_PATH.read_text(encoding="utf-8"))
        for entry in payload.get("landmarks", []):
            landmarks.append(Landmark(name=entry["name"], lat=entry["lat"], lon=entry["lon"], kind="poi"))
    return landmarks


LANDMARKS: list[Landmark] = _load()

_BY_NAME: dict[str, Landmark] = {}
_BY_STRIPPED: dict[str, Landmark] = {}
for _landmark in LANDMARKS:
    _BY_NAME.setdefault(squash_for_match(_landmark.name), _landmark)
    stripped = _strip_generic(_landmark.name)
    if stripped:
        _BY_STRIPPED.setdefault(stripped, _landmark)

_BY_ALIAS: dict[str, Landmark] = {}
if _LANDMARKS_PATH.exists():
    _curated = {
        entry["name"]: entry for entry in json.loads(_LANDMARKS_PATH.read_text(encoding="utf-8")).get("landmarks", [])
    }
    for _landmark in LANDMARKS:
        for _alias in _curated.get(_landmark.name, {}).get("aliases", []):
            _BY_ALIAS.setdefault(squash_for_match(_alias), _landmark)

# A single word identifies a place only when no other place uses it: "شریف"
# means دانشگاه شریف, but "شهدا" belongs to several stations at once and means
# nothing on its own.
_token_owners: dict[str, set[str]] = {}
for _landmark in LANDMARKS:
    for _token in _tokens(_landmark.name):
        _token_owners.setdefault(_token, set()).add(_landmark.name)
_BY_TOKEN: dict[str, Landmark] = {
    token: next(l for l in LANDMARKS if l.name == next(iter(owners)))
    for token, owners in _token_owners.items()
    if len(owners) == 1
}


def _fuzzy(needle: str) -> Optional[Landmark]:
    """The closest name, when it is close enough to be a misspelling of it.

    "تاتر شهر" for "تئاتر شهر" is the everyday case: one dropped letter, in a
    name most people have never had to write down.
    """
    if len(needle) < _MIN_FUZZY_LENGTH:
        return None
    best: Optional[Landmark] = None
    best_score = _FUZZY_THRESHOLD
    for index in (_BY_NAME, _BY_STRIPPED):
        for candidate, landmark in index.items():
            if abs(len(candidate) - len(needle)) > 3:
                continue
            score = SequenceMatcher(None, needle, candidate).ratio()
            if score > best_score:
                best, best_score = landmark, score
    return best


@lru_cache(maxsize=512)
def resolve(name: str) -> Optional[Landmark]:
    """Map one free-text Persian place name onto a point, or None.

    Tried in order of decreasing confidence: the full name, a curated alias,
    the name with its classifying word dropped, a word that only one place
    uses, and finally the nearest spelling.
    """
    needle = squash_for_match(name)
    if not needle:
        return None
    stripped = _strip_generic(name)

    for key in (needle, stripped):
        if not key:
            continue
        hit = _BY_NAME.get(key) or _BY_ALIAS.get(key) or _BY_STRIPPED.get(key) or _BY_TOKEN.get(key)
        if hit is not None:
            return hit

    for token in _tokens(name):
        hit = _BY_NAME.get(token) or _BY_ALIAS.get(token) or _BY_TOKEN.get(token)
        if hit is not None:
            return hit

    return _fuzzy(stripped or needle)
