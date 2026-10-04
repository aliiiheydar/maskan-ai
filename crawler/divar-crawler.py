"""Divar Tehran rental crawler.

Two stages, deliberately using two different mechanisms:

  1. DISCOVERY (headless browser). Divar's post list is a virtualised feed --
     the DOM only ever holds ~10-16 anchors no matter how far you scroll --
     and its `POST /v8/postlist/w/search` endpoint pages through opaque
     server-issued state (a `search_uid`, a base64 `viewed_tokens` blob and an
     ISO `last_post_date`). Rather than reconstruct that by hand we drive the
     real site in Chromium, scroll the feed's inner scroll container, and read
     the post tokens out of the search responses the page itself makes.
     A single result stream caps out around ~220 posts, so discovery is
     sharded across Tehran's ~450 district slugs -- visited in random order,
     so the crawl samples the city instead of draining all ~150,000 listings.
     Each district's quota is *proportional to how dense its market is*: a
     probe pass measures each shard's posting rate (see measure_density) and
     the target is divided out in proportion, so ونک contributes far more of
     the sample than a quiet outlying slug. The measurement is cached in
     district_density.json and reused until it goes stale.

  2. DETAIL (plain HTTP). `GET /v8/posts-v2/web/<token>` returns the whole
     widget tree as JSON and needs no browser, so spending a page load per
     listing would be pure waste.

Both stages are resumable: tokens seen and posts already fetched are
checkpointed to disk after every write.

Usage:
    python3 divar-crawler.py                     # sample ~10,000 listings, density-weighted
    python3 divar-crawler.py --target 3000       # smaller sample, same spread
    python3 divar-crawler.py --districts 40      # 40 randomly chosen districts
    python3 divar-crawler.py --seed 42           # reproduce a previous sample
    python3 divar-crawler.py --stage detail      # drain the existing queue only
    python3 divar-crawler.py --probe             # re-measure district density first
    python3 divar-crawler.py --uniform            # equal quota per district (the old behaviour)
    python3 divar-crawler.py -v                  # per-post diagnostics
"""

from __future__ import annotations

import argparse
import threading
import json
import logging
import math
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx

# The placeholder-price test lives in the backend so that the crawler, the
# preprocessor and the database purge can never disagree about what counts as
# a real price. See backend/app/data/price_plausibility.py.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app.data.price_plausibility import is_placeholder_row, load_price_floors  # noqa: E402

# The per-cell lower price limit measured against the built corpus (written by
# app.data.database.purge_local_price_outliers). Empty until that has been run,
# in which case the placeholder test falls back to its absolute floors -- a
# crawl on a fresh checkout behaves exactly as it did before.
price_floors = load_price_floors()

LOG = logging.getLogger("divar")

CITY_ID = "1"
CITY_SLUG = "tehran"
CATEGORY = "rent-apartment"

LIST_URL = "https://divar.ir/s/{city}/{category}"
DISTRICTS_API = f"https://api.divar.ir/v8/places/cities/{CITY_ID}/districts"
POST_API = "https://api.divar.ir/v8/posts-v2/web/"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "divar_listings.json")
SEEN_TOKENS_FILE = os.path.join(HERE, "crawled_tokens.json")
QUEUE_FILE = os.path.join(HERE, "discovered_tokens.json")
DENSITY_FILE = os.path.join(HERE, "district_density.json")

# Deposit-to-rent conversion rate from CLAUDE.md: 100M Tomans of ودیعه is worth
# about 3M Tomans of monthly اجاره, so a deposit contributes 3% of itself per
# month to the true cost of a lease.
TABDIL_MONTHLY_RATE = 0.03

# Monthly rent at or below this is Divar's placeholder for a رهن کامل lease
# (typically 10,000 Tomans), not a real rent figure.
FULL_RAHN_RENT_CEILING = 100_000

# Tehran carries roughly 150,000 active rental listings. This project neither
# needs nor wants that volume, so the crawl samples down to a workable set.
DEFAULT_TARGET_LISTINGS = 10_000
# Even when the target is small, take enough from each district that the
# sample says something about it rather than being noise.
MIN_TOKENS_PER_DISTRICT = 8
# ...and never so much from one district that it drowns out the rest. Tehran's
# densest slugs out-post the quietest by two orders of magnitude, and a purely
# proportional split would spend the whole budget on a handful of them.
MAX_TOKENS_PER_DISTRICT = 400

# A measured density older than this is re-probed: Tehran's rental market
# shifts seasonally, and a quota built on last spring's posting rates would
# oversample districts that have since gone quiet.
DENSITY_MAX_AGE_DAYS = 14
# Posting rates span orders of magnitude. Raising them to this power before
# normalising softens the split -- the densest district still earns the biggest
# quota, but the thin tail is not starved down to its floor.
DENSITY_EXPONENT = 0.75

# A single Divar result stream stops yielding new tokens after roughly this
# many; once the scroll loop stalls this often in a row the shard is spent.
# Post detail is a plain HTTP GET per token, so the stage is latency-bound,
# not CPU-bound: a serial crawl spends ~2.1s per post and would need six hours
# for a 10,000-post top-up. A handful of threads, each keeping the same
# politeness pause, brings that under an hour without raising the per-request
# rate any single worker asks of the host.
DEFAULT_DETAIL_WORKERS = 6

# Stands in for "no quota" in --exhaustive runs: larger than any single Divar
# result stream, so the scroll loop is bounded by the stall check alone.
_EXHAUSTIVE_QUOTA = 1_000_000

_SCROLL_STALL_LIMIT = 5
_SCROLL_MAX_STEPS = 60

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# CLAUDE.md invariant: Arabic yeh/kaf must be folded to their Persian forms
# before any text is compared or stored.
_ARABIC_FOLD = str.maketrans("يكئ", "یکی")

# Divar states amenities as positive or negative phrases ("آسانسور دارد" /
# "آسانسور ندارد") and carries the machine-readable identity in the icon name,
# so the icon is what we key on and the phrase only supplies the polarity.
_AMENITY_BY_ICON = {
    "ELEVATOR": "has_elevator",
    "PARKING": "has_parking",
    "CABINET": "has_storage",
    "STORAGE": "has_storage",
    "BALCONY": "has_balcony",
}
_AMENITY_BY_WORD = {
    "آسانسور": "has_elevator",
    "پارکینگ": "has_parking",
    "انباری": "has_storage",
    "بالکن": "has_balcony",
}

# Scrolls the feed's own scroll container. Divar keeps the post list inside a
# nested overflow element, so window.scrollTo does nothing and the lazy loader
# never fires.
_SCROLL_JS = """() => {
  const anchor = document.querySelector('a[href*="/v/"]');
  let el = anchor;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    if (el.scrollHeight > el.clientHeight + 50 && /auto|scroll/.test(style.overflowY)) {
      el.scrollTop = el.scrollHeight;
      return true;
    }
    el = el.parentElement;
  }
  window.scrollTo(0, document.body.scrollHeight);
  return false;
}"""


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------


def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_FOLD).strip()


def to_int(text: Any) -> Optional[int]:
    """First integer in a value, with Persian digits folded first."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    digits = re.sub(r"[^\d]", "", normalize(str(text)))
    return int(digits) if digits else None


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        LOG.warning("could not read %s, starting from %r", path, default)
        return default


def save_json(path: str, data: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # atomic, so an interrupt can never truncate the file


def build_client() -> httpx.Client:
    """An httpx client that ignores the shell's proxy environment.

    This machine exports ALL_PROXY=socks://... for a VPN; httpx reads proxy
    env vars by default and rejects the bare `socks://` scheme, which used to
    crash this script at client construction before it made a single request.
    Divar is an Iranian host and should be reached directly regardless.
    """
    return httpx.Client(
        trust_env=False,
        timeout=25.0,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa,en;q=0.9",
            "Origin": "https://divar.ir",
            "Referer": "https://divar.ir/",
        },
    )


# --------------------------------------------------------------------------
# stage 1: discovery
# --------------------------------------------------------------------------


# Divar's shard list and this project's محله polygons do not name the same
# places. Where a neighborhood we care about has no shard of its own, it is
# mapped onto the shard that geographically contains it -- measured against
# app/data/assets/gap_neighborhoods.geojson: the پارک لاله polygon sits
# entirely inside بلوار کشاورز's bounding box (overlap 1.0), while the next
# closest shard, فاطمی, covers only 53% of it.
_DISTRICT_ALIASES = {
    "پارک لاله": "bolvar-e-keshavarz",
}


def resolve_districts(districts: list[dict[str, Any]], selectors: list[str]) -> list[dict[str, Any]]:
    """Pick named shards out of Divar's district list.

    A selector may be a slug (`iranshahr`), Divar's alternate slug
    (`meydan-valiasr`), or the district's Persian name -- which is how the
    neighborhoods are written everywhere else in this project. Names are
    matched after the CLAUDE.md normalisation, so `فلسطین (میدان انقلاب)`
    typed with an Arabic yeh still lands on `enqelab`.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for district in districts:
        for key in (district.get("slug"), district.get("second_slug")):
            if key:
                by_key.setdefault(key, district)
        by_key.setdefault(normalize(district.get("name")), district)

    chosen: list[dict[str, Any]] = []
    missing: list[str] = []
    for raw in selectors:
        selector = raw.strip()
        if not selector:
            continue
        key = _DISTRICT_ALIASES.get(selector, selector)
        match = by_key.get(key) or by_key.get(normalize(key))
        if match is None:
            # Last resort: a substring of a district name, so that
            # `دانشگاه تهران` finds Divar's `دانشگاه تهران قدیمی`. The
            # shortest match wins, which keeps that from picking
            # `شهرک دانشگاه تهران قدیمی` instead.
            needle = normalize(key)
            candidates = [d for d in districts if needle and needle in normalize(d.get("name"))]
            match = min(candidates, key=lambda d: len(d.get("name", ""))) if candidates else None
        if match is None:
            missing.append(selector)
        elif match not in chosen:
            chosen.append(match)
            if normalize(match.get("name")) != normalize(selector):
                LOG.info("%s -> shard %s (%s)", selector, match["slug"], match.get("name"))

    if missing:
        raise SystemExit(
            "این محله‌ها در فهرست مناطق شناخته نشدند: " + "، ".join(missing)
        )
    return chosen


def shard_url(district: dict[str, Any]) -> str:
    """The result page for one district.

    Measured 2026-09-27: the path form this crawler used,
    `/s/tehran/rent-apartment/<slug>`, now answers
    "این صفحه حذف شده یا وجود ندارد" for districts whose `slug` and
    `second_slug` disagree -- `iranshahr`, `bolvar-e-keshavarz` and
    `tehran-university` among them -- so discovery silently harvested nothing
    from them. Only `second_slug` still resolves as a path, and the numeric id
    resolves as a query parameter. The id is what we send: it cannot go stale
    behind a rename, and the page title confirms the filter applied.
    """
    base = LIST_URL.format(city=CITY_SLUG, category=CATEGORY)
    return f"{base}?districts={district['id']}"


def shard_key(url: str) -> str:
    """The district identity inside a shard URL, for logs and density keys."""
    return url.rsplit("districts=", 1)[-1] if "districts=" in url else url.rsplit("/", 1)[-1]


def fetch_district_slugs(client: httpx.Client) -> list[dict[str, Any]]:
    response = client.get(DISTRICTS_API)
    response.raise_for_status()
    districts = response.json().get("districts", [])
    LOG.info("%d Tehran district shards available", len(districts))
    return districts


def _tokens_from_search_response(payload: dict) -> list[str]:
    tokens = []
    for widget in payload.get("list_widgets", []):
        token = widget.get("data", {}).get("action", {}).get("payload", {}).get("token")
        if token:
            tokens.append(token)
    return tokens


def _post_dates_from_search_response(payload: dict) -> list[str]:
    """ISO timestamps Divar attaches to a postlist page, newest first."""
    dates = []
    pagination = payload.get("pagination", {}) or {}
    for source in (pagination.get("data", {}), pagination, payload):
        value = source.get("last_post_date")
        if value:
            dates.append(str(value))
            break
    return dates


def _posting_rate(token_count: int, last_post_date: Optional[str]) -> Optional[float]:
    """Posts per hour, inferred from how far back one page of results reaches.

    Divar has no "how many listings are in this district" endpoint, so density
    is measured the way a hydrologist measures a river: by how fast it flows
    past a fixed point. One page of results is a fixed number of posts; the
    timestamp of the oldest of them says how long the district took to produce
    them. A dense market fills a page in an hour, a quiet one in a week.
    """
    if not last_post_date or token_count <= 0:
        return None
    try:
        oldest = datetime.fromisoformat(last_post_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - oldest).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return token_count / hours


def measure_density(shard_urls: list[str]) -> dict[str, float]:
    """One page load per district, returning {slug: posts per hour}.

    Costs one page load and a single scroll step per district -- roughly a
    tenth of the harvest pass it informs, since it never pages past the first
    response.

    The scroll is not optional. Divar server-renders the first page of results
    into the HTML, so a district whose feed the user never touches answers
    `wait_for_selector` without ever making a `postlist/w/search` request --
    and the timestamp this measurement needs lives only in that request's
    response. Without the nudge only the occasional district gets measured and
    every other one silently falls back to the median.
    """
    from playwright.sync_api import sync_playwright

    rates: dict[str, float] = {}
    captured: dict[str, object] = {}

    def on_response(response) -> None:
        if "postlist" not in response.url or "tokens" in captured:
            return
        try:
            payload = response.json()
        except Exception:
            return
        tokens = _tokens_from_search_response(payload)
        if not tokens:
            return
        captured["tokens"] = len(tokens)
        dates = _post_dates_from_search_response(payload)
        if dates:
            captured["last_post_date"] = dates[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
        page = browser.new_page(locale="fa-IR", viewport={"width": 1400, "height": 1000})
        page.on("response", on_response)
        try:
            for index, url in enumerate(shard_urls, start=1):
                slug = shard_key(url)
                captured.clear()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_selector('a[href*="/v/"]', timeout=25_000)
                    page.evaluate(_SCROLL_JS)
                    for _ in range(12):
                        page.wait_for_timeout(400)
                        if "tokens" in captured:
                            break
                except Exception:
                    LOG.debug("density probe found nothing for %s", slug)
                    continue
                rate = _posting_rate(int(captured.get("tokens", 0)), captured.get("last_post_date"))  # type: ignore[arg-type]
                if rate is not None:
                    rates[slug] = rate
                if index % 25 == 0 or index == len(shard_urls):
                    LOG.info("density probe %d/%d (%d measured)", index, len(shard_urls), len(rates))
        finally:
            browser.close()
    return rates


def load_density(max_age_days: int = DENSITY_MAX_AGE_DAYS) -> dict[str, float]:
    """The cached measurement, or {} when it is missing or stale."""
    payload = load_json(DENSITY_FILE, None)
    if not payload:
        return {}
    try:
        measured = datetime.fromisoformat(payload["measured_at"])
    except (KeyError, ValueError):
        return {}
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - measured).days > max_age_days:
        LOG.info("cached district density is older than %d days; re-probing", max_age_days)
        return {}
    return {str(slug): float(rate) for slug, rate in payload.get("rates", {}).items()}


def save_density(rates: dict[str, float]) -> None:
    save_json(DENSITY_FILE, {"measured_at": datetime.now(timezone.utc).isoformat(), "rates": rates})


def allocate_quotas(shard_urls: list[str], rates: dict[str, float], target: int) -> dict[str, int]:
    """Split `target` listings over the shards in proportion to their density.

    A district we could not measure is given the *median* measured rate rather
    than zero: an unmeasured district is one we know nothing about, not one we
    know to be empty, and starving it would quietly bias the sample toward the
    districts whose pages happened to load.
    """
    measured = sorted(rates.values())
    fallback = measured[len(measured) // 2] if measured else 1.0

    weights: dict[str, float] = {}
    for url in shard_urls:
        slug = shard_key(url)
        weights[url] = max(rates.get(slug, fallback), 1e-6) ** DENSITY_EXPONENT

    quotas: dict[str, int] = {}
    remaining = float(target)
    open_shards = dict(weights)
    # Clipping at MAX_TOKENS_PER_DISTRICT used to silently shrink the sample:
    # the budget taken off a dense district simply vanished instead of moving
    # to a district that could still absorb it, so `--target 10000` allocated
    # noticeably fewer than 10,000. Redistribute the clipped remainder over the
    # shards that are still under their ceiling, a few passes until it settles.
    for _ in range(6):
        if not open_shards or remaining <= 0:
            break
        total_weight = sum(open_shards.values()) or 1.0
        clipped: dict[str, float] = {}
        spent = 0.0
        for url, weight in open_shards.items():
            share = int(round(remaining * weight / total_weight))
            share = max(MIN_TOKENS_PER_DISTRICT, min(MAX_TOKENS_PER_DISTRICT, share))
            quotas[url] = share
            spent += share
            if share < MAX_TOKENS_PER_DISTRICT:
                clipped[url] = weight
        if len(clipped) == len(open_shards):
            break
        remaining = max(0.0, remaining - (spent - sum(quotas[u] for u in clipped)))
        open_shards = clipped
    for url in shard_urls:
        quotas.setdefault(url, MIN_TOKENS_PER_DISTRICT)
    return quotas


def discover_tokens(
    shard_urls: list[str],
    quotas: dict[str, int],
    known: set[str] | None = None,
    on_shard=None,
    labels: dict[str, str] | None = None,
) -> set[str]:
    """Drive Chromium over each shard URL and collect post tokens.

    Tehran carries on the order of 150,000 rental listings, far more than this
    project wants to fetch or store, so discovery samples rather than
    exhausts. Two things make the sample representative *at every moment*,
    not just once it completes:

      - `shard_urls` is expected to arrive already shuffled, so the districts
        are visited in random order;
      - each shard contributes at most `quotas[url]` tokens before we move on,
        instead of draining its full ~216-post stream. The quota is
        proportional to the district's measured posting density, so the sample
        mirrors where Tehran's rental market actually is rather than treating
        a slug with forty active adverts as the equal of one with four
        thousand.

    Together these mean a run stopped halfway still holds listings spread
    across the whole city rather than every listing in the alphabetically
    first districts. Capping per shard also makes the sweep far cheaper: a
    district yields its quota in one or two scrolls instead of a dozen.

    `known` is the set of tokens already crawled or queued by earlier runs.
    The quota is spent on tokens *outside* it: Divar's feed is recency-ordered,
    so a second sweep of a district re-shows the same posts the first sweep
    took, and counting those against the quota meant a top-up run stopped
    scrolling before it reached anything new -- the previous pass turned a
    10,000-listing target into 2,428 genuinely new tokens for exactly this
    reason. Scrolling now continues until the shard has yielded its quota of
    *unseen* posts, or the stream runs dry.

    `on_shard` is invoked with the accumulated token set after every shard so
    the caller can checkpoint the queue as it grows.
    """
    from playwright.sync_api import sync_playwright

    seen_before: set[str] = set(known or ())
    found: set[str] = set()
    shard_found: set[str] = set()

    def on_response(response) -> None:
        if "postlist" not in response.url:
            return
        try:
            payload = response.json()
        except Exception:
            return
        # Only the shard's raw harvest is recorded here; the quota is applied
        # once the shard finishes, so this must not write to `found` directly.
        shard_found.update(_tokens_from_search_response(payload))

    with sync_playwright() as playwright:
        # --no-proxy-server for the same reason build_client passes
        # trust_env=False: the VPN proxy must not sit in front of Divar.
        browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
        page = browser.new_page(locale="fa-IR", viewport={"width": 1400, "height": 1000})
        page.on("response", on_response)

        try:
            for index, url in enumerate(shard_urls, start=1):
                before = len(found)
                shard_found.clear()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_selector('a[href*="/v/"]', timeout=25_000)
                except Exception as error:
                    LOG.debug("shard %s yielded nothing (%s)", url, type(error).__name__)
                    continue

                # The first page of results arrives with the initial load, so a
                # district whose quota is already covered never has to scroll.
                per_shard = quotas.get(url, MIN_TOKENS_PER_DISTRICT)
                stale = seen_before | found

                def fresh() -> set[str]:
                    return shard_found - stale

                stalled = 0
                previous = len(shard_found)
                for _ in range(_SCROLL_MAX_STEPS):
                    if len(fresh()) >= per_shard:
                        break
                    page.evaluate(_SCROLL_JS)
                    page.wait_for_timeout(random.randint(1800, 2600))
                    stalled = stalled + 1 if len(shard_found) == previous else 0
                    previous = len(shard_found)
                    if stalled >= _SCROLL_STALL_LIMIT:
                        break  # this district holds fewer listings than its quota

                # Divar answers 26 posts per response, so the harvest usually
                # overshoots the quota. Committing a random subset rather than
                # the first N keeps the sample unbiased with respect to Divar's
                # own ordering, which is recency- and promotion-weighted.
                candidates = fresh()
                quota = min(per_shard, len(candidates))
                found.update(random.sample(sorted(candidates), quota))

                LOG.info(
                    "[%d/%d] %s -> +%d new of %d seen (%d fresh), quota %d (%d total)",
                    index, len(shard_urls), (labels or {}).get(url, shard_key(url)),
                    len(found) - before, len(shard_found), len(candidates), per_shard, len(found),
                )
                if on_shard is not None:
                    on_shard(found)
        finally:
            browser.close()

    return found


# --------------------------------------------------------------------------
# stage 2: post detail extraction
# --------------------------------------------------------------------------


def _iter_widgets(sections: Iterable[dict]) -> Iterable[tuple[str, str, dict]]:
    """Flatten the post's widget tree into (section, widget_type, data).

    Modal pages hang off SELECTOR_ROW actions and hold the long tail of the
    specification table -- building orientation, units per floor, kitchen type,
    pet policy -- so they are walked inline rather than treated separately.
    """
    for section in sections:
        name = section.get("section_name", "")
        for widget in section.get("widgets", []):
            data = widget.get("data", {})
            yield name, widget.get("widget_type", ""), data

            if widget.get("widget_type") == "EXPANDABLE_SECTION":
                for sub in data.get("widget_list", []):
                    yield name, sub.get("widget_type", ""), sub.get("data", {})

            action = data.get("action", {})
            if action.get("type") == "LOAD_MODAL_PAGE":
                modal = action.get("payload", {}).get("modal_page", {})
                for sub in modal.get("widget_list", []):
                    yield "MODAL", sub.get("widget_type", ""), sub.get("data", {})


def _extract_location(data: dict) -> dict:
    """Coordinates from a MAP_ROW.

    Divar signals precision by which sub-object is present -- `exact_data` for
    a pinned address, `fuzzy_data` (a point plus an obfuscation radius) when
    the advertiser only approved a neighbourhood-level pin. There is no
    discriminating `type` field, which is why an earlier version of this
    parser read `location["type"]` and silently produced null coordinates for
    every single listing.
    """
    location = data.get("location", {})
    if "exact_data" in location:
        point = location["exact_data"].get("point", {})
        return {
            "precision": "EXACT",
            "lat": point.get("latitude"),
            "lon": point.get("longitude"),
            "radius_meters": None,
        }
    if "fuzzy_data" in location:
        fuzzy = location["fuzzy_data"]
        point = fuzzy.get("point", {})
        return {
            "precision": "FUZZY",
            "lat": point.get("latitude"),
            "lon": point.get("longitude"),
            "radius_meters": fuzzy.get("radius"),
        }
    return {"precision": None, "lat": None, "lon": None, "radius_meters": None}


def _amenity_key(title: str, icon_name: str) -> Optional[str]:
    if icon_name in _AMENITY_BY_ICON:
        return _AMENITY_BY_ICON[icon_name]
    for word, key in _AMENITY_BY_WORD.items():
        if word in title:
            return key
    return None


def extract_post(token: str, raw: dict) -> dict:
    title = ""
    description = ""
    location_text = ""
    published_text = ""
    map_location = {"precision": None, "lat": None, "lon": None, "radius_meters": None}
    specs: dict[str, str] = {}
    attributes: dict[str, str] = {}
    amenities: dict[str, bool] = {}
    other_features: list[str] = []
    suitable_for: list[str] = []
    images: list[str] = []
    deposit = rent = convertible_deposit_max = None
    can_convert = False
    # Modal chip groups are only identified by the DESCRIPTION_ROW that
    # precedes them, so the last label seen decides what the next WRAPPER_ROW's
    # chips actually mean.
    modal_label = ""

    for section, widget_type, data in _iter_widgets(raw.get("sections", [])):
        if widget_type in ("LEGEND_TITLE_ROW", "TITLE_ROW") and section == "TITLE":
            title = data.get("title") or title

        elif widget_type == "EXPANDABLE_SECTION":
            location_text = normalize(data.get("title")) or location_text

        elif widget_type == "DESCRIPTION_ROW":
            text = data.get("text", "")
            if section == "DESCRIPTION":
                description = text
            elif "انتشار" in text:
                published_text = normalize(text)
            elif section == "MODAL":
                modal_label = normalize(text)

        elif widget_type == "GROUP_INFO_ROW":
            for item in data.get("items", []):
                specs[normalize(item.get("title"))] = normalize(item.get("value"))

        elif widget_type == "UNEXPANDABLE_ROW":
            key, value = normalize(data.get("title")), normalize(data.get("value"))
            if key and value:
                attributes[key] = value

        elif widget_type == "RENT_SLIDER":
            # The single richest widget on the page: the exact deposit and rent
            # as raw integers, plus the ceiling the advertiser will accept if
            # the tenant converts rent into deposit (تبدیل).
            deposit = to_int(data.get("credit", {}).get("value"))
            rent = to_int(data.get("rent", {}).get("value"))
            convertible_deposit_max = to_int(data.get("credit", {}).get("transformed_value"))
            can_convert = True

        elif widget_type == "GROUP_FEATURE_ROW":
            for item in data.get("items", []):
                item_title = normalize(item.get("title"))
                key = _amenity_key(item_title, item.get("icon", {}).get("icon_name", ""))
                present = "ندارد" not in item_title and item.get("available") is not False
                if key:
                    amenities[key] = present
                elif present and item_title:
                    other_features.append(item_title)

        elif widget_type == "FEATURE_ROW":
            feature_title = normalize(data.get("title"))
            if "قابل تبدیل" in feature_title:
                can_convert = True
                continue
            if not feature_title or data.get("disabled", False):
                continue
            # The modal repeats the headline amenities as prose ("بالکن دارد"),
            # so they are folded into the boolean set rather than dumped into
            # the free-text list where nothing can query them.
            key = _amenity_key(feature_title, data.get("icon", {}).get("icon_name", ""))
            if key:
                amenities.setdefault(key, "ندارد" not in feature_title)
            else:
                other_features.append(feature_title)

        elif widget_type == "WRAPPER_ROW" and section == "MODAL" and "مناسب برای" in modal_label:
            for chip in data.get("chip_list", {}).get("chips", []):
                if text := normalize(chip.get("text")):
                    suitable_for.append(text)

        elif widget_type in ("IMAGE_CAROUSEL", "IMAGE_SLIDER_ROW"):
            for item in data.get("items", []):
                url = item.get("image", {}).get("url") or item.get("image_url")
                if url:
                    images.append(url)

        elif widget_type == "MAP_ROW":
            map_location = _extract_location(data)

    webengage = raw.get("webengage", {})
    web_info = raw.get("seo", {}).get("web_info", {})

    # webengage carries the same figures as clean integers, so it backstops a
    # listing that has no RENT_SLIDER (a fully-رهن unit with no monthly rent).
    if deposit is None:
        deposit = to_int(webengage.get("credit"))
    if rent is None:
        rent = to_int(webengage.get("rent"))

    # "۲ از ۳" -> floor 2 of 3 total.
    floor = total_floors = None
    if floor_text := attributes.get("طبقه"):
        numbers = re.findall(r"\d+", floor_text)
        floor = int(numbers[0]) if numbers else None
        total_floors = int(numbers[1]) if len(numbers) > 1 else None
    if total_floors is None:
        total_floors = to_int(attributes.get("تعداد کل طبقات ساختمان"))

    effective_cost = None
    if rent is not None and deposit is not None:
        effective_cost = int(rent + deposit * TABDIL_MONTHLY_RATE)

    # A رهن کامل listing is advertised with a token monthly rent rather than a
    # zero, so a plain `rent == 0` test would miss almost all of them.
    is_full_rahn = rent is not None and rent <= FULL_RAHN_RENT_CEILING

    build_year_text = specs.get("ساخت", "")

    return {
        "token": token,
        "url": f"https://divar.ir/v/{token}",
        "title": normalize(title) or normalize(web_info.get("title")),
        "description": description,
        # --- money (Tomans, int64 per CLAUDE.md) ---
        "deposit_toman": deposit,
        "rent_toman": rent,
        "effective_monthly_cost": effective_cost,
        "can_convert": can_convert,
        "convertible_deposit_max_toman": convertible_deposit_max,
        "is_full_rahn": is_full_rahn,
        # --- property ---
        "area_sqm": to_int(specs.get("متراژ")),
        "rooms": to_int(specs.get("اتاق")),
        "build_year": to_int(build_year_text),
        "build_year_text": build_year_text,
        "build_year_is_upper_bound": "قبل از" in build_year_text,
        "floor": floor,
        "total_floors": total_floors,
        "has_elevator": amenities.get("has_elevator"),
        "has_parking": amenities.get("has_parking"),
        "has_storage": amenities.get("has_storage"),
        "has_balcony": amenities.get("has_balcony"),
        # --- geography ---
        "lat": map_location["lat"],
        "lon": map_location["lon"],
        "location_precision": map_location["precision"],
        "location_radius_meters": map_location["radius_meters"],
        "neighborhood": normalize(web_info.get("district_persian")),
        "neighborhood_slug": webengage.get("district"),
        "city": normalize(web_info.get("city_persian")) or "تهران",
        "location_text": location_text,
        # --- provenance ---
        "category": webengage.get("cat_3") or CATEGORY,
        "business_type": webengage.get("business_type"),
        "published_text": published_text,
        "unavailable_after": raw.get("seo", {}).get("unavailable_after"),
        "image_count": webengage.get("image_count"),
        "images": images,
        # --- long tail, kept raw for later mining ---
        "attributes": attributes,
        "other_features": sorted(set(other_features)),
        "suitable_for": sorted(set(suitable_for)),
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def fetch_post(client: httpx.Client, token: str, max_retries: int = 4) -> Optional[dict]:
    delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            response = client.get(f"{POST_API}{token}")
            if response.status_code == 200:
                return extract_post(token, response.json())
            if response.status_code in (403, 429):
                LOG.warning("rate limited on %s (HTTP %s); backing off %.0fs", token, response.status_code, delay)
                time.sleep(delay)
                delay *= 2
            elif response.status_code == 404:
                LOG.debug("%s is gone (404)", token)
                return None
            else:
                LOG.debug("HTTP %s on %s, retry %d/%d", response.status_code, token, attempt, max_retries)
                time.sleep(2)
        except Exception as error:
            LOG.debug("network error on %s: %s, retry %d/%d", token, error, attempt, max_retries)
            time.sleep(3)
    return None


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl Divar Tehran rental listings.")
    parser.add_argument("--stage", choices=["all", "list", "detail"], default="all")
    parser.add_argument("--districts", type=int, default=0, help="limit discovery to N district shards (0 = all)")
    parser.add_argument(
        "--only", default="",
        help="crawl only these districts: comma-separated slugs or Persian names "
             "(e.g. 'ایرانشهر,میدان ولیعصر'). Skips the random city-wide sample.",
    )
    parser.add_argument(
        "--exhaustive", action="store_true",
        help="take every advert each selected shard will show instead of a quota "
             "(only meaningful with --only)",
    )
    parser.add_argument("--limit", type=int, default=0, help="stop after fetching N new posts (0 = no limit)")
    parser.add_argument(
        "--target", type=int, default=DEFAULT_TARGET_LISTINGS,
        help="how many listings to sample city-wide; sets each district's discovery quota",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_DETAIL_WORKERS,
        help="parallel post-detail fetchers (1 = the old serial crawl)",
    )
    parser.add_argument("--seed", type=int, default=None, help="seed the district shuffle for a reproducible sample")
    parser.add_argument("--probe", action="store_true", help="re-measure district density before discovery")
    parser.add_argument("--uniform", action="store_true", help="equal quota per district instead of density-weighted")
    parser.add_argument(
        "--keep-placeholder-prices", action="store_true",
        help="keep adverts priced at a token figure (ودیعه ۱٬۰۰۰) instead of discarding them",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s",
        datefmt="%H:%M:%S",
    )
    # -v is for this crawler's own diagnostics; httpx/httpcore debug-log every
    # header of every request, which drowns them out entirely.
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # A logged seed makes an otherwise random sample reproducible after the
    # fact, which matters when a downstream ranking result needs explaining.
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    random.seed(seed)
    LOG.info("sampling ~%d listings with seed %d", args.target, seed)

    listings: list[dict] = load_json(DATA_FILE, [])
    crawled: set[str] = set(load_json(SEEN_TOKENS_FILE, []))
    queue: set[str] = set(load_json(QUEUE_FILE, []))

    LOG.info("resuming with %d listings, %d crawled tokens, %d queued", len(listings), len(crawled), len(queue))
    client = build_client()

    try:
        if args.stage in ("all", "list"):
            districts = fetch_district_slugs(client)
            selectors = [part for part in args.only.split(",") if part.strip()]
            if selectors:
                # A named run is not a sample, so none of the sampling
                # machinery applies: no shuffle (there is nothing to be
                # unbiased about when every shard asked for is crawled), no
                # truncation, and no density-weighted quota.
                districts = resolve_districts(districts, selectors)
                LOG.info(
                    "crawling %d named districts: %s",
                    len(districts), "، ".join(d.get("name", d["slug"]) for d in districts),
                )
            else:
                # Shuffle before any truncation, so --districts N is itself a
                # random sample of the city rather than the alphabetical head of it.
                random.shuffle(districts)
                if args.districts:
                    districts = districts[: args.districts]

            # The city-wide shard is deliberately left out: it adds no
            # geographic information and its ordering is promotion-weighted.
            shards = [shard_url(d) for d in districts]
            shard_names = {shard_url(d): d.get("name", d["slug"]) for d in districts}

            if args.exhaustive:
                # No cap: discovery then stops only when a shard's stream runs
                # dry (_SCROLL_STALL_LIMIT), which is what "every advert in
                # this محله" means in practice -- Divar's own feed stops
                # yielding new tokens after roughly 216 per district.
                quotas = {url: _EXHAUSTIVE_QUOTA for url in shards}
                LOG.info("%d districts, draining each shard completely", len(districts))
            elif args.uniform:
                per_shard = max(MIN_TOKENS_PER_DISTRICT, math.ceil(args.target / max(1, len(districts))))
                quotas = {url: per_shard for url in shards}
                LOG.info("%d districts x %d listings each (uniform)", len(districts), per_shard)
            else:
                rates = {} if args.probe else load_density()
                # A cache measured under the old URL scheme is keyed by slug,
                # not district id, so it matches nothing here -- and
                # allocate_quotas would quietly hand every district the median
                # rate instead of saying so. Re-probe unless most of the
                # shards we are about to visit are actually in it.
                if rates and sum(shard_key(u) in rates for u in shards) < len(shards) // 2:
                    LOG.info("cached density does not cover these shards; re-probing")
                    rates = {}
                if not rates:
                    LOG.info("measuring posting density across %d districts", len(shards))
                    rates = measure_density(shards)
                    if rates:
                        save_density(rates)
                quotas = allocate_quotas(shards, rates, args.target)
                busiest = sorted(quotas.items(), key=lambda item: -item[1])[:5]
                LOG.info(
                    "%d districts, density-weighted quotas %d..%d; busiest: %s",
                    len(districts), min(quotas.values()), max(quotas.values()),
                    "، ".join(f"{shard_names.get(u, shard_key(u))}={q}" for u, q in busiest),
                )

            def checkpoint(found: set[str]) -> None:
                save_json(QUEUE_FILE, sorted((queue | found) - crawled))

            discovered = discover_tokens(
                shards, quotas, known=crawled | queue, on_shard=checkpoint, labels=shard_names,
            )
            queue |= discovered - crawled
            save_json(QUEUE_FILE, sorted(queue))
            LOG.info("discovery finished: %d tokens queued", len(queue))

        if args.stage in ("all", "detail"):
            # Shuffled for the same reason the districts are: if fetching is
            # interrupted, what landed on disk is still spread across Tehran
            # rather than clustered in whichever districts sorted first.
            pending = sorted(queue - crawled)
            random.shuffle(pending)
            if args.limit:
                pending = pending[: args.limit]
            workers = max(1, args.workers)
            LOG.info("fetching %d posts with %d workers", len(pending), workers)
            dropped_placeholders = 0

            # Each worker keeps its own client: httpx connection pools are not
            # meant to be shared across threads, and a client per worker also
            # gives each one its own keep-alive connection to the host.
            local = threading.local()
            pool_clients: list[httpx.Client] = []
            clients_lock = threading.Lock()

            def fetch_one(token: str) -> tuple[str, Optional[dict]]:
                worker_client = getattr(local, "client", None)
                if worker_client is None:
                    worker_client = local.client = build_client()
                    with clients_lock:
                        pool_clients.append(worker_client)
                post = fetch_post(worker_client, token)
                # The pause stays per worker rather than global: every worker
                # still waits between its own requests, exactly as the serial
                # crawl did, so no single connection speeds up.
                time.sleep(random.uniform(1.2, 2.4))
                return token, post

            executor = ThreadPoolExecutor(max_workers=workers)
            futures = [executor.submit(fetch_one, token) for token in pending]
            try:
                for index, future in enumerate(as_completed(futures), start=1):
                    token, post = future.result()
                    crawled.add(token)
                    queue.discard(token)
                # An advert priced at a token ۱٬۰۰۰ تومان is withholding its
                # price, not stating it. Two tests: an absolute floor no real
                # Tehran lease sits under, and -- once the corpus has been
                # measured -- the local floor for the square kilometre the
                # advert stands in, which is what catches a figure that is
                # ordinary for the city and impossible for that street.
                # This is the cheap first pass: it runs on the advertised
                # area, so a listing whose متراژ is itself nonsense survives
                # here and is caught by the preprocessor, which re-tests once
                # the area has been repaired. The token stays in `crawled`
                # either way, so a resumed run does not spend a request
                # fetching it again.
                    if post and not args.keep_placeholder_prices and is_placeholder_row(post, price_floors):
                        dropped_placeholders += 1
                        post = None
                    if post:
                        listings.append(post)
                        LOG.debug(
                            "[%d/%d] %s | %s | %sm2 | %s | (%s,%s)",
                            index, len(pending), token, post["title"][:32], post["area_sqm"],
                            post["neighborhood"], post["lat"], post["lon"],
                        )

                    # Only this loop touches the checkpoint files; the workers
                    # return their post and nothing else, so no lock is needed
                    # around the listing list or the token sets.
                    if index % 25 == 0 or index == len(pending):
                        save_json(DATA_FILE, listings)
                        save_json(SEEN_TOKENS_FILE, sorted(crawled))
                        save_json(QUEUE_FILE, sorted(queue))
                        LOG.info("[%d/%d] saved, %d listings total", index, len(pending), len(listings))
            except KeyboardInterrupt:
                for pendingfuture in futures:
                    pendingfuture.cancel()
                raise
            finally:
                executor.shutdown(wait=False)
                for worker_client in pool_clients:
                    worker_client.close()

            if dropped_placeholders:
                LOG.info("discarded %d adverts with a placeholder price", dropped_placeholders)

    except KeyboardInterrupt:
        LOG.warning("interrupted; saving before exit")
    finally:
        save_json(DATA_FILE, listings)
        save_json(SEEN_TOKENS_FILE, sorted(crawled))
        save_json(QUEUE_FILE, sorted(queue))
        client.close()
        LOG.info("done: %d listings stored in %s", len(listings), DATA_FILE)

    return 0


if __name__ == "__main__":
    sys.exit(main())
