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
    neighborhood_key: Optional[str] = Field(
        default=None,
        description="Stable key into matched_neighborhoods.geojson; the join between a listing and its polygon",
    )
    district: Optional[str] = Field(default=None, description="Official Tehran municipal district, e.g. 'منطقه 6'")

    # Financials (In Tomans)
    deposit_toman: int = Field(ge=0, description="ودیعه / رهن (تومان)")
    rent_toman: int = Field(ge=0, description="اجاره ماهیانه (تومان)")
    effective_monthly_cost: int = Field(ge=0, description="rent + (deposit * 0.03)")
    can_convert: bool = Field(default=True, description="قابلیت تبدیل ودیعه و اجاره")
    convertible_deposit_max_toman: Optional[int] = Field(
        default=None,
        ge=0,
        description="Ceiling the advertiser accepts if the tenant converts rent into deposit (تبدیل). "
        "Divar exposes this on its rent slider; absent means the band is inferred.",
    )
    is_shared_living: bool = Field(
        default=False,
        description="Not a whole property to live in: a room/bed/flatmate advert or a parking space "
        "let on its own. Offered in the app as هم‌خانه و خوابگاه; see app/core/shared_living.py.",
    )
    is_full_rahn: bool = Field(
        default=False,
        description="رهن کامل. Advertised with a token monthly rent rather than a literal zero, "
        "so this is a flag rather than a rent == 0 test.",
    )

    # Physical Attributes
    area_sqm: int = Field(gt=10, description="متراژ زیربنا (مترمربع)")
    rooms: int = Field(ge=0, le=10, description="تعداد اتاق خواب")
    # Basements are real stock in Tehran and Divar lists them as منفی ۱/۲, so
    # the floor axis has to reach below zero -- the scoring engine applies a
    # daylight penalty to them rather than pretending they don't exist.
    floor: int = Field(ge=-2, le=40, description="طبقه واحد (۰ = همکف، منفی = زیرزمین)")
    total_floors: int = Field(default=5, ge=0, le=40)
    has_elevator: bool = Field(default=False)
    has_parking: bool = Field(default=False)
    has_balcony: bool = Field(default=False)
    has_storage: bool = Field(default=True)
    building_age_years: int = Field(default=5)
    build_year: Optional[int] = Field(default=None, description="سال ساخت (شمسی), as advertised")

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

    # Rich attributes carried over from the real Divar feed. All optional: a
    # synthetic row simply has none of them, and the ranking engine treats a
    # missing value as "the ad is silent", never as a no.
    location_precision: Optional[str] = Field(
        default=None, description="EXACT | FUZZY | NEIGHBORHOOD -- how literally lat/lon should be read"
    )
    location_radius_meters: Optional[int] = Field(
        default=None, description="Divar blurs some points; the pin is somewhere inside this radius"
    )
    units_per_floor: Optional[int] = Field(default=None, ge=0)
    min_contract_months: Optional[int] = Field(default=None, ge=0)
    direction: Optional[str] = Field(default=None, description="جهت ساختمان: شمالی/جنوبی/شرقی/غربی")
    kitchen_type: Optional[str] = Field(default=None, description="نوع آشپزخانه: اپن/جزیره/بسته/نیمه اپن")
    is_renovated: bool = Field(default=False)
    is_furnished: bool = Field(default=False)
    has_pool: bool = Field(default=False)
    has_sauna: bool = Field(default=False)
    has_jacuzzi: bool = Field(default=False)
    pets_policy: Optional[str] = Field(default=None, description="allowed | not_allowed | negotiable")
    features: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Divar's other_features grouped by facet: cooling, heating, floor_material, water_heater, wc_type",
    )
    suitable_for: list[str] = Field(default_factory=list, description="مناسب برای: خانواده/زوج/مجرد/دانشجو")
    attributes: dict[str, str] = Field(
        default_factory=dict, description="Divar's مشخصات table verbatim, for the detail page"
    )
    provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Per field, where its value came from: divar_structured, divar_attribute, listing_text, "
        "estimated_from_area, ... The detail page marks text-derived values so a user can tell an "
        "advertiser's typed fact from something we read out of their prose.",
    )
    published_text: Optional[str] = Field(default=None, description="Persian publication/refresh dates as advertised")

    # Provenance & media
    source: str = Field(default="synthetic", description="Where the row came from, e.g. 'divar' or 'synthetic'")
    source_url: Optional[str] = Field(default=None)
    image_count: int = Field(default=0, ge=0)
    images: list[str] = Field(default_factory=list)
    images_are_authentic: bool = Field(
        default=True, description="Advertiser answered 'تصویرها برای همین ملک است؟' with بله"
    )

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    embedding: Optional[list[float]] = Field(default=None, description="1536-dim vector")
