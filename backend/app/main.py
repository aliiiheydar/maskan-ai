"""FastAPI application entrypoint. Run with:
uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.media import close_client as close_media_client
from app.api.v1.router import api_router
from app.data import database
from app.data.repository import ListingRepository
from app.data.synthetic_generator import generate_synthetic_listings
from app.llm.client import OpenRouterClient, flush_embedding_cache

# Spread across the 258 real neighborhood polygons, so this is roughly a dozen
# listings per محله -- enough that narrowing to one neighborhood plus a budget
# and an area range still returns a usable set rather than nothing.
SYNTHETIC_LISTING_COUNT = 3000


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.llm_client = OpenRouterClient()
    app.state.repository = ListingRepository()

    # The real corpus lives in SQLite (scripts/build_database.py). Generating a
    # synthetic one is the fallback for a checkout that has never built it --
    # the app comes up either way, rather than failing on a missing file.
    if database.listing_count():
        count = app.state.repository.open()
        print(f"[maskan] loaded {count} listings from {database.DEFAULT_DB_PATH.name}")
    else:
        print("[maskan] no database found; falling back to the synthetic corpus")
        app.state.repository.seed(await generate_synthetic_listings(app.state.llm_client, SYNTHETIC_LISTING_COUNT))
        # The corpus is re-embedded on every reload otherwise; with a real
        # embedding key that is a live bill for vectors we already computed.
        flush_embedding_cache()

    try:
        yield
    finally:
        app.state.repository.close()
        await close_media_client()
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
