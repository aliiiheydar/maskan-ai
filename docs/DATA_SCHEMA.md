# Data Schema & Entity Specifications

## 1. Core Listing Entity (`Listing`)

Every real estate listing in the system follows this strict schema:

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

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
    lat: float = Field(ge=35.5500, le=35.8500, description="WGS84 Latitude (Tehran)")
    lon: float = Field(ge=51.1000, le=51.6000, description="WGS84 Longitude (Tehran)")
    h3_index: str = Field(description="Uber H3 Resolution 8 index string")
    nearest_metro_id: str = Field(description="Nearest station ID from station graph")
    nearest_metro_name: str = Field(description="Nearest station name in Persian")
    dist_to_metro_meters: float = Field(ge=0)
    metro_walk_mins: float = Field(ge=0, description="dist_to_metro_meters / 80.0")
    in_tarh_terafik: bool = Field(default=False)
    in_tarh_aloodegi: bool = Field(default=False)
    
    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    embedding: Optional[list[float]] = Field(default=None, description="1536-dim vector")
```

## 2. Intent Extraction Schema (`ExtractedSearchIntent`)

The structured object extracted by DeepSeek V4 Flash from user chat:

```python
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
        description="e.g. ['نورگیر عالی', 'کوچه خلوت', 'نوساز']"
    )
    soft_preference_summary: str = Field(
        default="",
        description="Persian summary of soft preferences used for semantic embedding search"
    )
```

## 3. Synthetic Data Generation Distribution Rules

When generating the 1,000 synthetic listings in `app/data/synthetic_generator.py`:
* **Neighborhood Anchors**:
  - `سعادت‌آباد / شهرک غرب`: Lat 35.78, Lon 51.37 | Deposit: 500M–2B | Rent: 20M–80M | Area: 80–180m² | Elevator: 90%
  - `یوسف‌آباد / امیرآباد / فاطمی`: Lat 35.72, Lon 51.40 | Deposit: 200M–800M | Rent: 12M–35M | Area: 60–120m² | Elevator: 60%
  - `صادقیه / پونک / جنت‌آباد`: Lat 35.73, Lon 51.33 | Deposit: 200M–600M | Rent: 10M–25M | Area: 55–110m² | Elevator: 75%
  - `میدان انقلاب / دانشگاه شریف`: Lat 35.70, Lon 51.36 | Deposit: 100M–400M | Rent: 7M–18M | Area: 40–85m² | Elevator: 40%
  - `تهرانپارس / نارمک`: Lat 35.73, Lon 51.52 | Deposit: 150M–500M | Rent: 8M–22M | Area: 50–100m² | Elevator: 70%
