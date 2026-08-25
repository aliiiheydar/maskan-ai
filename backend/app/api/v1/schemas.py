"""Request/response DTOs for the v1 API wire format. See docs/API_SPEC.md.

Distinct from app.core.models: those are the fixed domain entities
(Listing, ExtractedSearchIntent); these are the HTTP-facing shapes.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class BBoxFilter(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class UnifiedSearchRequest(BaseModel):
    mode: Literal["intelligent", "classic", "map"] = "classic"
    query_text: Optional[str] = None
    neighborhoods: list[str] = Field(default_factory=list)
    max_deposit_toman: Optional[int] = Field(default=None, ge=0)
    max_rent_toman: Optional[int] = Field(default=None, ge=0)
    min_area_sqm: Optional[int] = Field(default=None, gt=0)
    rooms: Optional[int] = Field(default=None, ge=0)
    requires_elevator: bool = False
    requires_parking: bool = False
    workplace_lat: Optional[float] = None
    workplace_lon: Optional[float] = None
    max_commute_mins: Optional[int] = None
    bbox: Optional[BBoxFilter] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ListingResult(BaseModel):
    id: str
    title: str
    neighborhood: str
    deposit_toman: int
    rent_toman: int
    area_sqm: int
    floor: int
    has_elevator: bool
    has_parking: bool
    lat: float
    lon: float
    dist_to_metro_mins: float
    commute_to_work_mins: Optional[float] = None
    utility_score: float
    tier: int
    trade_off_rationale: Optional[str] = None


class SearchResponse(BaseModel):
    natural_language_summary: str
    tier_1_results: list[ListingResult]
    tier_2_results: list[ListingResult]
    total_count: int


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


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
