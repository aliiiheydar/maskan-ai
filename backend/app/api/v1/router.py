"""Aggregates all v1 routers. Mounted at /api/v1 in app.main."""

from fastapi import APIRouter

from app.api.v1 import chat, listings, search, transit

api_router = APIRouter()
api_router.include_router(search.router)
api_router.include_router(chat.router)
api_router.include_router(listings.router)
api_router.include_router(transit.router)
