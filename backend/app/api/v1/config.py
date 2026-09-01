"""GET /api/v1/config -- what this deployment can actually do.

The AI features are the only optional part of the product: they need an
OpenRouter key, and a checkout without one is a perfectly working classic
search rather than a broken app. The client has no other way to know that --
it would otherwise find out by offering جستجوی هوشمند, letting the user type a
sentence, and answering with a 503 -- so the capability is published here and
read once at startup.
"""

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_llm_client
from app.api.v1.schemas import AppConfig
from app.llm.client import OpenRouterClient

router = APIRouter()


@router.get("/config", response_model=AppConfig)
async def get_config(client: OpenRouterClient = Depends(get_llm_client)) -> AppConfig:
    return AppConfig(ai_search_enabled=client.has_real_api_key())
