"""Single source of truth for deployment settings and Tehran domain constants."""

from typing import NamedTuple

from pydantic_settings import BaseSettings, SettingsConfigDict


class BBox(NamedTuple):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


# Tehran city bounding box (WGS84).
TEHRAN_BBOX = BBox(min_lat=35.5500, max_lat=35.8500, min_lon=51.1000, max_lon=51.6000)

# Approximate central-Tehran congestion-pricing zone (Tarh-e Terafik), roughly the
# Vali-e-Asr / Enghelab / Ferdowsi corridor. This is an MVP bounding-box
# simplification, NOT the legally exact odd/even-day polygon.
TARH_TERAFIK_BBOX = BBox(min_lat=35.7000, max_lat=35.7350, min_lon=51.3900, max_lon=51.4350)

# Tabdil (deposit <-> rent conversion).
TABDIL_RATE: float = 0.03

# Walking speed used for metro/BRT walk-time estimates.
WALK_SPEED_MPM: float = 80.0

# Multiplier applied to driving time when a trip touches the congestion zone.
CONGESTION_PENALTY: float = 1.4

# Average speed assumptions for commute-time estimation (Tehran MVP placeholders).
AVG_DRIVE_SPEED_KMH: float = 22.0
AVG_TRANSIT_SPEED_KMH: float = 28.0
TRANSIT_TRANSFER_BUFFER_MINS: float = 5.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openrouter_api_key: str = "your_openrouter_api_key_here"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-chat"
    embedding_model: str = "openai/text-embedding-3-small"
    default_lat: float = 35.6997
    default_lon: float = 51.3380
    app_env: str = "development"
    debug: bool = True


settings = Settings()
