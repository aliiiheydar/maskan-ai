"""Extracted search intent domain model. Field-for-field per docs/DATA_SCHEMA.md."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core import constants


class CriteriaWeights(BaseModel):
    """How much each MAUT sub-utility matters to *this* user.

    The classic filter panel has no way to express this, so it leaves the
    weights unset and the documented constants (docs/ALGORITHMS.md SS2) apply.
    The conversational path can infer them -- "مهم‌ترین چیز برام نزدیکی به مترو
    است، قیمت مهم نیست" is a statement about weights, not about filters -- and
    a set of weights here replaces the constants for that search only.
    Values are relative; they are normalized to sum to 1 before use.
    """

    budget: float = Field(default=0.0, ge=0.0, description="How far under the stated budget the home is")
    value: float = Field(default=0.0, ge=0.0, description="Price against the neighborhood's own median per m2")
    area: float = Field(default=0.0, ge=0.0, description="Closeness to the ideal size")
    amenity: float = Field(default=0.0, ge=0.0, description="Parking, elevator, storage, balcony")
    metro: float = Field(default=0.0, ge=0.0, description="Walking distance to the nearest metro station")
    commute: float = Field(default=0.0, ge=0.0, description="Reachability of the stated workplace")
    quality: float = Field(default=0.0, ge=0.0, description="How sought-after the neighborhood itself is")
    freshness: float = Field(default=0.0, ge=0.0, description="Building age")
    soft: float = Field(default=0.0, ge=0.0, description="Match with the described qualities")

    _FIELDS = ("budget", "value", "area", "amenity", "metro", "commute", "quality", "freshness", "soft")

    def total(self) -> float:
        return sum(getattr(self, name) for name in self._FIELDS)

    def normalized(self) -> "CriteriaWeights":
        total = self.total()
        if total <= 0:
            return CriteriaWeights()
        return CriteriaWeights(**{name: getattr(self, name) / total for name in self._FIELDS})


class ExtractedSearchIntent(BaseModel):
    # Hard Financial Caps (in Tomans)
    min_deposit: Optional[int] = Field(default=None, description="حداقل ودیعه (تومان)")
    max_deposit: Optional[int] = Field(default=None, description="سقف ودیعه (تومان)")
    min_rent: Optional[int] = Field(default=None, description="حداقل اجاره ماهیانه (تومان)")
    max_rent: Optional[int] = Field(default=None, description="سقف اجاره ماهیانه (تومان)")
    can_convert: bool = Field(default=True)

    # Hard Filters
    min_area_sqm: Optional[int] = Field(default=None)
    max_area_sqm: Optional[int] = Field(default=None, description="سقف متراژ (مترمربع)")
    min_rooms: Optional[int] = Field(default=None)
    min_floor: Optional[int] = Field(default=None, description="حداقل طبقه (منفی = زیرزمین)")
    max_floor: Optional[int] = Field(default=None, description="حداکثر طبقه")
    min_build_year: Optional[int] = Field(default=None, description="سال ساخت از (شمسی) -- نوساز")
    must_have_elevator: bool = Field(default=False)
    must_have_parking: bool = Field(default=False)
    must_have_storage: bool = Field(default=False, description="انباری")
    must_have_balcony: bool = Field(default=False, description="بالکن")
    must_have_images: bool = Field(default=False, description="فقط آگهی‌های دارای عکس")
    full_rahn_only: bool = Field(default=False, description="فقط رهن کامل")
    # Shared homes, rooms and dormitory beds are priced per person and would
    # otherwise dominate the cheap end of every ranking. They are a separate
    # market, chosen explicitly, not mixed in: "standard" excludes them,
    # "shared" returns only them.
    living_kind: Literal["standard", "shared"] = "standard"
    convertible_only: bool = Field(default=False, description="فقط موارد قابل تبدیل")
    target_neighborhoods: list[str] = Field(
        default_factory=list, description="Persian neighborhood names as stated by the user"
    )
    # Resolved from target_neighborhoods against matched_neighborhoods.geojson.
    # The search area is a hard filter decided by polygon containment, so the
    # keys -- not the names -- are what the filter actually runs on.
    target_neighborhood_keys: list[str] = Field(default_factory=list)

    # Commute Target Hub
    workplace_lat: Optional[float] = Field(default=None)
    workplace_lon: Optional[float] = Field(default=None)
    workplace_name: Optional[str] = Field(default=None)
    max_commute_mins: int = Field(default=45)
    commute_importance: float = Field(
        default=constants.COMMUTE_IMPORTANCE_DEFAULT,
        ge=0.0,
        le=1.0,
        description="0..1 dial on how much reachability should weigh in the ranking. "
        "0 drops the commute criterion and redistributes its weight.",
    )
    financial_persona: Literal["prefer_higher_rent", "prefer_higher_deposit", "balanced"] = Field(
        default="balanced",
        description="Which side of a تبدیل the user wants to be pushed toward: "
        "prefer_higher_rent protects liquidity, prefer_higher_deposit protects monthly cash flow.",
    )
    commute_mode: Literal["walk", "transit", "drive"] = Field(
        default="transit", description="Mode used to estimate commute time to workplace_lat/lon"
    )

    # Soft Preferences
    soft_preferences: list[str] = Field(
        default_factory=list,
        description="e.g. ['نورگیر عالی', 'کوچه خلوت', 'نوساز']",
    )
    soft_preference_summary: str = Field(
        default="",
        description="Persian summary of soft preferences used for semantic embedding search",
    )

    # Ranking Weights (conversational path only -- see CriteriaWeights)
    weights: Optional[CriteriaWeights] = Field(default=None)
