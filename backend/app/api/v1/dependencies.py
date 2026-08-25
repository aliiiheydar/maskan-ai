"""FastAPI dependency providers for shared, app-lifespan-scoped state."""

from fastapi import Request

from app.data.repository import ListingRepository
from app.llm.client import OpenRouterClient


def get_llm_client(request: Request) -> OpenRouterClient:
    return request.app.state.llm_client


def get_repository(request: Request) -> ListingRepository:
    return request.app.state.repository
