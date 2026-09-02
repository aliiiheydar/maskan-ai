"""POST /api/v1/search -- one endpoint for all three ways of searching."""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_llm_client, get_repository
from app.api.v1.schemas import ListingResult, MapCluster, MapPoint, SearchResponse, UnifiedSearchRequest
from app.search.map_clusters import cluster_matches
from app.core.models import ExtractedSearchIntent, Listing
from app.core.normalizers import to_persian_digits
from app.data.repository import ListingRepository
from app.llm.client import LLMUnavailableError, OpenRouterClient
from app.llm.intent_extractor import extract_search_intent
from app.search.scoring import ScoredListing, hard_constraint_mask, rank_listings, weights_from_importance
from app.spatial import neighborhoods
from app.spatial.transit import estimate_commute_time

router = APIRouter()


# --- ranked-result cache ---------------------------------------------------
#
# Ranking is a pure function of (corpus, intent, viewport): the same filters
# asked twice must produce the same order, or the feed would reshuffle under
# the user. That makes it cacheable, and worth caching, because the ways this
# endpoint is used repeat the same query constantly -- paging with "بیشتر" is
# the *same* search asking for rows 60..90, panning back to a viewport just
# left is the same search again, and toggling a filter off returns to the one
# before it. Without this, every one of those re-scored the whole city.
#
# Only the head of the ranking is kept, not the whole list: a cache entry is
# then a few hundred references rather than tens of thousands, so the cache
# costs megabytes instead of hundreds of them. A page past the head (which no
# UI in this app can reach -- the feed pages 60 then 30 at a time) simply
# misses and is ranked in full.
_CACHE_MAX_ENTRIES = 64
_CACHE_HEAD_RESULTS = 600


@dataclass
class _RankedPage:
    scored: list[ScoredListing]
    total_count: int
    summary: str
    map_points: list[MapPoint]
    map_clusters: list[MapCluster]


_cache: "OrderedDict[tuple, _RankedPage]" = OrderedDict()


def _cache_key(
    repository: ListingRepository, payload: UnifiedSearchRequest, intent: ExtractedSearchIntent
) -> tuple:
    """Everything the ranking depends on, and nothing else.

    The corpus is identified by size: the database is loaded once at startup
    and replaced only by a restart, so a differing count is the only way the
    rows under a live process can change. Page and page size are deliberately
    absent -- that is the whole point, one ranking serving every page of it.
    """
    bbox = (
        (payload.bbox.min_lat, payload.bbox.min_lon, payload.bbox.max_lat, payload.bbox.max_lon)
        if payload.bbox
        else None
    )
    return (
        len(repository),
        payload.mode,
        bbox,
        payload.map_zoom,
        payload.rooms,
        intent.model_dump_json(exclude_unset=False),
    )


def _cache_get(key: tuple) -> Optional[_RankedPage]:
    entry = _cache.get(key)
    if entry is not None:
        _cache.move_to_end(key)
    return entry


def _cache_put(key: tuple, entry: _RankedPage) -> None:
    _cache[key] = entry
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


async def _build_intent(payload: UnifiedSearchRequest, client: OpenRouterClient) -> ExtractedSearchIntent:
    if payload.mode == "chat" and payload.query_text:
        if not client.has_real_api_key():
            raise HTTPException(
                status_code=503,
                detail="جستجوی گفت‌وگویی پیکربندی نشده است. لطفاً از پنل جستجو و رتبه‌بندی استفاده کنید.",
            )
        try:
            intent = await extract_search_intent(client, payload.query_text)
        except LLMUnavailableError as error:
            raise HTTPException(status_code=503, detail=error.persian_message) from error
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail="در تحلیل درخواست شما مشکلی پیش آمد. لطفاً دوباره یا با جمله‌ای ساده‌تر تلاش کنید.",
            ) from error
    else:
        intent = ExtractedSearchIntent()

    overrides: dict = {}
    if payload.min_deposit_toman is not None:
        overrides["min_deposit"] = payload.min_deposit_toman
    if payload.max_deposit_toman is not None:
        overrides["max_deposit"] = payload.max_deposit_toman
    if payload.min_rent_toman is not None:
        overrides["min_rent"] = payload.min_rent_toman
    if payload.max_rent_toman is not None:
        overrides["max_rent"] = payload.max_rent_toman
    if payload.min_area_sqm is not None:
        overrides["min_area_sqm"] = payload.min_area_sqm
    if payload.max_area_sqm is not None:
        overrides["max_area_sqm"] = payload.max_area_sqm
    if payload.min_floor is not None:
        overrides["min_floor"] = payload.min_floor
    if payload.max_floor is not None:
        overrides["max_floor"] = payload.max_floor
    if payload.min_build_year is not None:
        overrides["min_build_year"] = payload.min_build_year
    if payload.requires_elevator:
        overrides["must_have_elevator"] = True
    if payload.requires_parking:
        overrides["must_have_parking"] = True
    if payload.requires_storage:
        overrides["must_have_storage"] = True
    if payload.requires_balcony:
        overrides["must_have_balcony"] = True
    if payload.requires_images:
        overrides["must_have_images"] = True
    if payload.full_rahn_only:
        overrides["full_rahn_only"] = True
    # Always sent, never inferred: which of the two markets is being searched
    # is the user's explicit choice, and the default is whole units.
    overrides["living_kind"] = payload.living_kind
    if payload.criteria_importance:
        overrides["weights"] = weights_from_importance(payload.criteria_importance)
    if payload.convertible_only:
        overrides["convertible_only"] = True
    if payload.commute_importance is not None:
        overrides["commute_importance"] = payload.commute_importance
    if payload.financial_persona is not None:
        overrides["financial_persona"] = payload.financial_persona
    if payload.neighborhoods:
        overrides["target_neighborhoods"] = payload.neighborhoods
    if payload.workplace_lat is not None:
        overrides["workplace_lat"] = payload.workplace_lat
    if payload.workplace_lon is not None:
        overrides["workplace_lon"] = payload.workplace_lon
    if payload.max_commute_mins is not None:
        overrides["max_commute_mins"] = payload.max_commute_mins
    if payload.commute_mode is not None:
        overrides["commute_mode"] = payload.commute_mode

    resolved = intent.model_copy(update=overrides) if overrides else intent

    # The search area is a hard geometric filter, so whatever names came from
    # the client or the LLM are resolved to polygon keys once, here, and every
    # downstream check runs on the keys.
    keys = neighborhoods.normalize_keys(resolved.target_neighborhoods)
    return resolved.model_copy(update={"target_neighborhood_keys": keys})


def _prefilter(repository: ListingRepository, payload: UnifiedSearchRequest, intent: ExtractedSearchIntent) -> list[Listing]:
    """Narrow the corpus down to the rows this query is about.

    Everything here is an *exact* predicate, so it is handed to the repository
    to answer from its indexes (R*Tree for the viewport, column indexes for the
    rest) rather than by walking the corpus in Python. The inexact parts of the
    query -- the tabdil-converted budget ceilings and the tolerance band around
    the area -- stay in ``hard_constraint_mask``, which runs on what survives.
    """
    bbox = (payload.bbox.min_lat, payload.bbox.min_lon, payload.bbox.max_lat, payload.bbox.max_lon) if payload.bbox else None
    return repository.query(intent, bbox=bbox, min_rooms=payload.rooms)


def _to_result(scored: ScoredListing, intent: ExtractedSearchIntent) -> ListingResult:
    commute_mins = None
    if intent.workplace_lat is not None and intent.workplace_lon is not None:
        commute_mins = estimate_commute_time(
            scored.listing.lat, scored.listing.lon, intent.workplace_lat, intent.workplace_lon, mode=intent.commute_mode
        )
    return ListingResult(
        id=scored.listing.id,
        title=scored.listing.title,
        neighborhood=scored.listing.neighborhood,
        neighborhood_key=scored.listing.neighborhood_key,
        district=scored.listing.district,
        deposit_toman=scored.listing.deposit_toman,
        rent_toman=scored.listing.rent_toman,
        area_sqm=scored.listing.area_sqm,
        rooms=scored.listing.rooms,
        floor=scored.listing.floor,
        total_floors=scored.listing.total_floors,
        build_year=scored.listing.build_year,
        has_elevator=scored.listing.has_elevator,
        has_parking=scored.listing.has_parking,
        has_storage=scored.listing.has_storage,
        has_balcony=scored.listing.has_balcony,
        can_convert=scored.listing.can_convert,
        is_full_rahn=scored.listing.is_full_rahn,
        image_count=scored.listing.image_count,
        thumbnail_url=scored.listing.images[0] if scored.listing.images else None,
        source_url=scored.listing.source_url,
        suggested_deposit_toman=scored.suggested_deposit_toman,
        suggested_rent_toman=scored.suggested_rent_toman,
        lat=scored.listing.lat,
        lon=scored.listing.lon,
        dist_to_metro_mins=scored.listing.metro_walk_mins,
        commute_to_work_mins=commute_mins,
        utility_score=round(scored.utility_score, 3),
        trade_off_rationale=scored.trade_off_rationale,
        is_pareto_optimal=scored.is_pareto_optimal,
        score_breakdown={name: round(value, 3) for name, value in scored.score_breakdown.items()},
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: UnifiedSearchRequest,
    client: OpenRouterClient = Depends(get_llm_client),
    repository: ListingRepository = Depends(get_repository),
) -> SearchResponse:
    intent = await _build_intent(payload, client)

    key = _cache_key(repository, payload, intent)
    cached = _cache_get(key)
    wanted_through = _page_start(payload) + payload.page_size
    if cached is not None and (
        wanted_through <= len(cached.scored) or len(cached.scored) == cached.total_count
    ):
        return _respond(cached, payload, intent)

    candidates = _prefilter(repository, payload, intent)

    if payload.mode == "map":
        # Map-explore is a plain boolean filter, not the weighted utility
        # ranking -- there's no "best" pin when you're panning the map, so
        # every hard-constraint match is surfaced equally, unsorted, instead
        # of being reordered by Utility(L|U).
        ranked = [
            ScoredListing(listing=listing, utility_score=0.0)
            for listing in candidates
            if hard_constraint_mask(listing, intent)
        ]
        summary = f"{to_persian_digits(len(ranked))} مورد در این محدوده از نقشه یافت شد."
    else:
        # Baselines come from the whole corpus, not from the candidate slice:
        # "cheap for this neighborhood" has to be measured against the
        # neighborhood, not against whatever survived the user's filters.
        ranked = await rank_listings(client, candidates, intent, repository.baselines)
        # No LLM prose above the feed: it repeated what the cards already
        # show, cost a chat round-trip on every keystroke-debounced search,
        # and delayed results behind a generation the user did not ask for.
        summary = f"{to_persian_digits(len(ranked))} مورد یافت شد."

    map_points: list[MapPoint] = []
    map_clusters: list[MapCluster] = []
    if payload.mode == "map":
        # Map mode accounts for every match, not just the page -- but as a mix
        # of pins and counted cells rather than ten thousand pins. The split is
        # made server-side against the viewport that was asked about, so the
        # browser never receives, or re-clusters, more than it can draw.
        cells, drawn = cluster_matches([s.listing for s in ranked], payload.bbox, payload.map_zoom)
        map_points = [MapPoint(id=l.id, lat=l.lat, lon=l.lon) for l in drawn]
        map_clusters = [MapCluster(**vars(cell)) for cell in cells]

    head = max(_CACHE_HEAD_RESULTS, wanted_through)
    entry = _RankedPage(
        scored=ranked[:head],
        total_count=len(ranked),
        summary=summary,
        map_points=map_points,
        map_clusters=map_clusters,
    )
    _cache_put(key, entry)
    return _respond(entry, payload, intent)


def _page_start(payload: UnifiedSearchRequest) -> int:
    """The first row of the requested page.

    ``offset`` wins when the client sends one, because only the client knows
    where its own list ends -- see UnifiedSearchRequest.offset. The page
    arithmetic remains for callers whose pages are all the same size.
    """
    return payload.offset if payload.offset is not None else (payload.page - 1) * payload.page_size


def _respond(entry: _RankedPage, payload: UnifiedSearchRequest, intent: ExtractedSearchIntent) -> SearchResponse:
    """One ranking, sliced into the page that was asked for.

    ``total_count`` is the full match count, not the page's: the feed prints
    it above the list and pages into it with "بیشتر".
    """
    start = _page_start(payload)
    page = entry.scored[start : start + payload.page_size]

    return SearchResponse(
        natural_language_summary=entry.summary,
        results=[_to_result(s, intent) for s in page],
        map_points=entry.map_points,
        map_clusters=entry.map_clusters,
        total_count=entry.total_count,
        applied_intent=intent,
    )
