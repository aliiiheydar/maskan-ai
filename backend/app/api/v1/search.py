"""POST /api/v1/search -- unified boolean-filter / map-bbox / AI search."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_llm_client, get_repository
from app.api.v1.schemas import ListingResult, SearchResponse, UnifiedSearchRequest
from app.core.models import ExtractedSearchIntent, Listing
from app.data.repository import ListingRepository
from app.llm.client import OpenRouterClient
from app.llm.dialogue_generator import generate_summary
from app.llm.intent_extractor import extract_search_intent
from app.search.scoring import ScoredListing, rank_listings
from app.spatial.transit import estimate_commute_time

router = APIRouter()


async def _build_intent(payload: UnifiedSearchRequest, client: OpenRouterClient) -> ExtractedSearchIntent:
    if payload.mode == "intelligent" and payload.query_text:
        if not client.has_real_api_key():
            raise HTTPException(status_code=503, detail="Intelligent search requires an OpenRouter API key.")
        intent = await extract_search_intent(client, payload.query_text)
    else:
        intent = ExtractedSearchIntent()

    overrides: dict = {}
    if payload.max_deposit_toman is not None:
        overrides["max_deposit"] = payload.max_deposit_toman
    if payload.max_rent_toman is not None:
        overrides["max_rent"] = payload.max_rent_toman
    if payload.min_area_sqm is not None:
        overrides["min_area_sqm"] = payload.min_area_sqm
    if payload.requires_elevator:
        overrides["must_have_elevator"] = True
    if payload.requires_parking:
        overrides["must_have_parking"] = True
    if payload.neighborhoods:
        overrides["target_neighborhoods"] = payload.neighborhoods
    if payload.workplace_lat is not None:
        overrides["workplace_lat"] = payload.workplace_lat
    if payload.workplace_lon is not None:
        overrides["workplace_lon"] = payload.workplace_lon
    if payload.max_commute_mins is not None:
        overrides["max_commute_mins"] = payload.max_commute_mins

    return intent.model_copy(update=overrides) if overrides else intent


def _prefilter(listings: list[Listing], payload: UnifiedSearchRequest) -> list[Listing]:
    """Query-level filters not covered by the utility formula's hard mask
    (see app.search.scoring.hard_constraint_mask's docstring)."""
    result = listings
    if payload.neighborhoods:
        result = [listing for listing in result if listing.neighborhood in payload.neighborhoods]
    if payload.rooms is not None:
        result = [listing for listing in result if listing.rooms >= payload.rooms]
    if payload.bbox:
        b = payload.bbox
        result = [listing for listing in result if b.min_lat <= listing.lat <= b.max_lat and b.min_lon <= listing.lon <= b.max_lon]
    return result


def _to_result(scored: ScoredListing, intent: ExtractedSearchIntent) -> ListingResult:
    commute_mins = None
    if intent.workplace_lat is not None and intent.workplace_lon is not None:
        commute_mins = estimate_commute_time(
            scored.listing.lat, scored.listing.lon, intent.workplace_lat, intent.workplace_lon, mode="transit"
        )
    return ListingResult(
        id=scored.listing.id,
        title=scored.listing.title,
        neighborhood=scored.listing.neighborhood,
        deposit_toman=scored.listing.deposit_toman,
        rent_toman=scored.listing.rent_toman,
        area_sqm=scored.listing.area_sqm,
        floor=scored.listing.floor,
        has_elevator=scored.listing.has_elevator,
        has_parking=scored.listing.has_parking,
        lat=scored.listing.lat,
        lon=scored.listing.lon,
        dist_to_metro_mins=scored.listing.metro_walk_mins,
        commute_to_work_mins=commute_mins,
        utility_score=round(scored.utility_score, 3),
        tier=scored.tier,
        trade_off_rationale=scored.trade_off_rationale,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: UnifiedSearchRequest,
    client: OpenRouterClient = Depends(get_llm_client),
    repository: ListingRepository = Depends(get_repository),
) -> SearchResponse:
    intent = await _build_intent(payload, client)
    candidates = _prefilter(repository.all(), payload)
    tier1, tier2 = await rank_listings(client, candidates, intent)

    # docs/API_SPEC.md doesn't define how page/page_size interact with the
    # two tiers; this paginates over the combined, tier-1-first ranking and
    # re-splits the page by tier, so total_count is the full match count and
    # tier boundaries stay intact within a page.
    combined = tier1 + tier2
    start = (payload.page - 1) * payload.page_size
    page = combined[start : start + payload.page_size]

    summary = await generate_summary(client, tier1, intent)

    return SearchResponse(
        natural_language_summary=summary,
        tier_1_results=[_to_result(s, intent) for s in page if s.tier == 1],
        tier_2_results=[_to_result(s, intent) for s in page if s.tier == 2],
        total_count=len(combined),
    )
