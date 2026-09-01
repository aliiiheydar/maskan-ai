"""Request/response DTOs for the v1 API wire format. See docs/API_SPEC.md.

Distinct from app.core.models: those are the fixed domain entities
(Listing, ExtractedSearchIntent); these are the HTTP-facing shapes.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.models import ExtractedSearchIntent


class BBoxFilter(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class UnifiedSearchRequest(BaseModel):
    mode: Literal["intelligent", "classic", "map"] = "classic"
    query_text: Optional[str] = None
    # Neighborhood keys from GET /geo/neighborhoods. Persian titles are also
    # accepted and resolved server-side, so a hand-written request works too.
    neighborhoods: list[str] = Field(default_factory=list)
    min_deposit_toman: Optional[int] = Field(default=None, ge=0)
    max_deposit_toman: Optional[int] = Field(default=None, ge=0)
    min_rent_toman: Optional[int] = Field(default=None, ge=0)
    max_rent_toman: Optional[int] = Field(default=None, ge=0)
    min_area_sqm: Optional[int] = Field(default=None, gt=0)
    max_area_sqm: Optional[int] = Field(default=None, gt=0)
    rooms: Optional[int] = Field(default=None, ge=0)
    min_floor: Optional[int] = Field(default=None, ge=-2, le=40)
    max_floor: Optional[int] = Field(default=None, ge=-2, le=40)
    # سال ساخت (شمسی). A floor rather than an age, matching how Iranian
    # listings state it.
    min_build_year: Optional[int] = Field(default=None, ge=1300, le=1500)
    requires_elevator: bool = False
    requires_parking: bool = False
    requires_storage: bool = False
    requires_balcony: bool = False
    requires_images: bool = False
    full_rahn_only: bool = False
    # Which market to search: whole units ("standard", the default) or shared
    # homes, rooms and dormitory beds ("shared"). Never both -- their prices
    # are not comparable, see app/core/shared_living.py.
    living_kind: Literal["standard", "shared"] = "standard"
    convertible_only: bool = False
    workplace_lat: Optional[float] = None
    workplace_lon: Optional[float] = None
    max_commute_mins: Optional[int] = None
    commute_mode: Optional[Literal["walk", "transit", "drive"]] = None
    # 0..1 dial on how much reachability weighs in the ranking; see
    # ExtractedSearchIntent.commute_importance.
    commute_importance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Per-criterion ranking importance from the filter panel's three-step
    # pickers: {"budget": "high", "metro": "low", ...}. Unnamed criteria keep
    # their documented default share. Criterion names are the fields of
    # CriteriaWeights; anything else is ignored rather than rejected, so an
    # older client cannot break a search.
    criteria_importance: dict[str, Literal["low", "normal", "high"]] = Field(default_factory=dict)
    financial_persona: Optional[Literal["prefer_higher_rent", "prefer_higher_deposit", "balanced"]] = None
    bbox: Optional[BBoxFilter] = None
    # The map's current zoom, so the server can decide which cells to send as
    # counted badges and which to open into pins (see app/search/map_clusters).
    # Fractional: the map zooms continuously rather than in whole levels.
    map_zoom: Optional[float] = Field(default=None, ge=0, le=22)
    page: int = Field(default=1, ge=1)
    # The ranked modes page 20-30 at a time; map-explore asks for a whole
    # viewport at once, since a cluster badge is only meaningful if it counts
    # every listing in the area rather than the first page of them.
    page_size: int = Field(default=20, ge=1, le=500)
    # Where this page starts, for a client whose pages are not all one size.
    # The feed offers 60 results up front and then 30 at a time, so
    # (page - 1) * page_size stopped describing where its next page began: it
    # asked for row 30 while already holding 60, and was handed rows 30..59 a
    # second time -- the same listings again, at the higher scores they had
    # ranked at, which read in the feed as the match percentage jumping back
    # up mid-list. A client that knows how many rows it holds says so, and
    # the two sides can no longer disagree about it.
    offset: Optional[int] = Field(default=None, ge=0)


class ListingResult(BaseModel):
    id: str
    title: str
    neighborhood: str
    neighborhood_key: Optional[str] = None
    district: Optional[str] = None
    deposit_toman: int
    rent_toman: int
    area_sqm: int
    rooms: int
    floor: int
    total_floors: int
    build_year: Optional[int] = None
    has_elevator: bool
    has_parking: bool
    has_storage: bool = False
    has_balcony: bool = False
    can_convert: bool = True
    is_full_rahn: bool = False
    image_count: int = 0
    thumbnail_url: Optional[str] = None
    source_url: Optional[str] = None
    # The (deposit, rent) split the engine had to assume to make this listing
    # fit the user's budget -- present only when it differs from the advertised
    # one, so the UI can say "با تبدیل" instead of silently showing a price the
    # advertiser never published.
    suggested_deposit_toman: Optional[int] = None
    suggested_rent_toman: Optional[int] = None
    lat: float
    lon: float
    dist_to_metro_mins: float
    commute_to_work_mins: Optional[float] = None
    utility_score: float
    tier: int
    trade_off_rationale: Optional[str] = None
    # Pareto-optimal on (effective cost, metro walk, area) among the Tier 1
    # set -- i.e. no other primary pick beats it on all three at once.
    is_pareto_optimal: bool = False
    # Per-criterion sub-utilities behind utility_score, so the UI can explain
    # a match rather than only assert a percentage.
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class MapPoint(BaseModel):
    """The whole of a listing that a map pin needs: where to draw it, which
    colour to draw it, and what to ask for when it is clicked.

    Only the matches the server chose to draw individually arrive this way;
    the denser parts of the viewport come back as MapCluster badges instead,
    so a pan costs a few hundred pins rather than the whole corpus. The feed
    stays paginated, so these cannot be the paginated ``ListingResult``
    objects -- at ~40 fields each they are far too heavy; this is the same
    listing at ~40 bytes, and the card details are fetched from
    GET /listings/{id} when a pin is actually clicked."""

    id: str
    lat: float
    lon: float
    tier: Literal[1, 2]


class MapCluster(BaseModel):
    """A counted group of matches, with the rectangle it covers.

    The count is what the badge shows; the rectangle is where the map flies
    when it is clicked, which is what makes a badge an invitation to go in
    rather than a dead end."""

    lat: float
    lon: float
    count: int
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class SearchResponse(BaseModel):
    natural_language_summary: str
    tier_1_results: list[ListingResult]
    tier_2_results: list[ListingResult]
    # Every match, unpaginated -- see MapPoint. Empty outside map mode, where
    # the ranked feed and its pins are the same paginated set.
    map_points: list[MapPoint] = Field(default_factory=list)
    # The rest of the map's matches, as counted cells. Together with
    # map_points these account for every match in the viewport, so the badges
    # still add up to the count above the feed.
    map_clusters: list[MapCluster] = Field(default_factory=list)
    total_count: int
    # What the search actually ran with, after free-text extraction and
    # neighborhood resolution. The UI reflects this back into the filter
    # panel, so an inferred filter is visible and correctable rather than
    # silently applied.
    applied_intent: Optional[ExtractedSearchIntent] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class IsochroneResponse(BaseModel):
    mode: Literal["walk", "transit", "drive"]
    geometry: Optional[dict] = None


class CongestionZone(BaseModel):
    zone: Literal["tarh_terafik", "tarh_aloodegi"]
    label: str
    geometry: dict


class NeighborhoodSummary(BaseModel):
    """One neighborhood without its polygon: enough for the filter picker and
    for the map to decide where and when to draw its label, but ~250x smaller
    than shipping all 258 outlines to every client on load."""

    key: str
    title: str
    subtitle: str = ""
    center_lat: float
    center_lon: float
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    # How big the محله actually is. The client sizes its first page of
    # results by the area being searched -- a selection covering a third of
    # the city should not open with the same thirty cards as one street -- and
    # a bounding box would overstate an irregular shape by half.
    area_sqkm: float = 0.0


class NeighborhoodShape(BaseModel):
    key: str
    title: str
    geometry: dict


class SearchArea(BaseModel):
    """The selected neighborhoods dissolved into a single outline.

    The picker's selection is a list of polygons, but what the map has to draw
    is one *area*: where two chosen neighborhoods touch, the border between
    them is an artefact of how the city is subdivided, not a boundary of the
    search. Unioning them server-side is also where the geometry library
    already is -- doing it in the browser would mean shipping a polygon-clipping
    dependency to every client to redraw the same shape.
    """

    keys: list[str]
    geometry: Optional[dict] = None


class CityBoundary(BaseModel):
    name: str
    geometry: dict


class TransitStation(BaseModel):
    id: str
    name: str
    name_en: Optional[str] = None
    lat: float
    lon: float
    type: str
    lines: list[str]
    has_elevator: bool
    relations: list[str]
