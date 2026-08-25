"""FastAPI application entrypoint. Run with:
uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.data.repository import ListingRepository
from app.data.synthetic_generator import generate_synthetic_listings
from app.llm.client import OpenRouterClient

SYNTHETIC_LISTING_COUNT = 1000


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.repository = ListingRepository()
    app.state.repository.seed(generate_synthetic_listings(SYNTHETIC_LISTING_COUNT))
    app.state.llm_client = OpenRouterClient()
    try:
        yield
    finally:
        await app.state.llm_client.close()


app = FastAPI(title="Maskan AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
