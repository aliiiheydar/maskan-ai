"""Listing domain model. Field-for-field per docs/DATA_SCHEMA.md."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import TEHRAN_BBOX


class Listing(BaseModel):
    id: str = Field(description="Unique identifier, e.g. 'teh-1001'")
    title: str = Field(description="Persian title, e.g. '۸۵ متر دوخوابه، رو به آفتاب'")
    description: str = Field(description="Detailed Persian description with soft traits")
    neighborhood: str = Field(description="Canonical district name, e.g. 'یوسف‌آباد'")

    # Financials (In Tomans)
    deposit_toman: int = Field(ge=0, description="ودیعه / رهن (تومان)")
    rent_toman: int = Field(ge=0, description="اجاره ماهیانه (تومان)")
    effective_monthly_cost: int = Field(ge=0, description="rent + (deposit * 0.03)")
    can_convert: bool = Field(default=True, description="قابلیت تبدیل ودیعه و اجاره")

    # Physical Attributes
    area_sqm: int = Field(gt=10, description="متراژ زیربنا (مترمربع)")
    rooms: int = Field(ge=0, le=5, description="تعداد اتاق خواب")
    floor: int = Field(ge=0, le=30, description="طبقه واحد (۰ = همکف)")
    total_floors: int = Field(default=5)
    has_elevator: bool = Field(default=False)
    has_parking: bool = Field(default=False)
    has_balcony: bool = Field(default=False)
    has_storage: bool = Field(default=True)
    building_age_years: int = Field(default=5)

    # Spatial & Transit Attributes
    lat: float = Field(ge=TEHRAN_BBOX.min_lat, le=TEHRAN_BBOX.max_lat, description="WGS84 Latitude (Tehran)")
    lon: float = Field(ge=TEHRAN_BBOX.min_lon, le=TEHRAN_BBOX.max_lon, description="WGS84 Longitude (Tehran)")
    h3_index: str = Field(description="Uber H3 Resolution 8 index string")
    nearest_metro_id: str = Field(description="Nearest station ID from station graph")
    nearest_metro_name: str = Field(description="Nearest station name in Persian")
    dist_to_metro_meters: float = Field(ge=0)
    metro_walk_mins: float = Field(ge=0, description="dist_to_metro_meters / 80.0")
    in_tarh_terafik: bool = Field(default=False)
    in_tarh_aloodegi: bool = Field(default=False)

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    embedding: Optional[list[float]] = Field(default=None, description="1536-dim vector")
