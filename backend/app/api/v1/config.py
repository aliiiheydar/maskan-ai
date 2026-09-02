"""GET /api/v1/config and /api/v1/health -- what this deployment is.

Which search modes exist is a property of the deployment, not of the client,
and the client has no other way to find out. Without this it would offer
جستجوی گفت‌وگویی, let the user type a sentence, and answer with a 503; it would
offer کاوش نقشه on a checkout that switched the map off. Both capabilities are
published here and read once at startup.

The two are missing for different reasons. The AI mode needs an OpenRouter key
and a checkout without one is a perfectly working ranked search rather than a
broken app, so its absence is a fact about the environment. The explore map is
switched off on purpose (EXPLORE_MAP_ENABLED), which is a product decision.
"""

from fastapi import APIRouter, Depends, Request

from app.api.v1.dependencies import get_llm_client
from app.api.v1.schemas import AppConfig, HealthReport
from app.core.config import settings
from app.llm.client import OpenRouterClient

router = APIRouter()


@router.get("/config", response_model=AppConfig)
async def get_config(client: OpenRouterClient = Depends(get_llm_client)) -> AppConfig:
    return AppConfig(
        ai_search_enabled=client.has_real_api_key(),
        explore_map_enabled=settings.explore_map_enabled,
    )


@router.get("/health", response_model=HealthReport)
async def health(request: Request) -> HealthReport:
    """Is this process up, and does it have a corpus to search?

    Both, because "up" on its own is not the question anyone is asking. A
    backend that came up on the 3,000-listing synthetic fallback -- an unpacked
    seed that failed, a volume that did not mount -- answers every request
    perfectly well and returns the wrong city, and the only cheap way to notice
    is that this number is not the one it should be. Docker's healthcheck and a
    human curl both read the same line.
    """
    return HealthReport(status="ok", listings=len(request.app.state.repository))
