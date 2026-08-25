"""Extracted search intent domain model. Field-for-field per docs/DATA_SCHEMA.md."""

from typing import Optional

from pydantic import BaseModel, Field


class ExtractedSearchIntent(BaseModel):
    # Hard Financial Caps (in Tomans)
    max_deposit: Optional[int] = Field(default=None, description="سقف ودیعه (تومان)")
    max_rent: Optional[int] = Field(default=None, description="سقف اجاره ماهیانه (تومان)")
    can_convert: bool = Field(default=True)

    # Hard Filters
    min_area_sqm: Optional[int] = Field(default=None)
    min_rooms: Optional[int] = Field(default=None)
    must_have_elevator: bool = Field(default=False)
    must_have_parking: bool = Field(default=False)
    target_neighborhoods: list[str] = Field(default_factory=list)

    # Commute Target Hub
    workplace_lat: Optional[float] = Field(default=None)
    workplace_lon: Optional[float] = Field(default=None)
    workplace_name: Optional[str] = Field(default=None)
    max_commute_mins: int = Field(default=45)

    # Soft Preferences
    soft_preferences: list[str] = Field(
        default_factory=list,
        description="e.g. ['نورگیر عالی', 'کوچه خلوت', 'نوساز']",
    )
    soft_preference_summary: str = Field(
        default="",
        description="Persian summary of soft preferences used for semantic embedding search",
    )
