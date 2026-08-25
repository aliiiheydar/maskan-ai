import json
from typing import Any, AsyncIterator, Optional

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.dependencies import get_llm_client
from app.main import app


class FakeChatClient:
    """Stands in for OpenRouterClient in tests that need a real API key path,
    without ever touching the network."""

    def has_real_api_key(self) -> bool:
        return True

    async def stream_chat_completion(self, messages: list[dict[str, str]], model: Optional[str] = None) -> AsyncIterator[str]:
        for token in ["سلام", "! چند مورد پیدا کردم."]:
            yield token

    async def chat_completion(
        self, messages: list[dict[str, str]], json_mode: bool = True, model: Optional[str] = None
    ) -> dict[str, Any]:
        return {"max_rent": 15_000_000, "must_have_elevator": True, "target_neighborhoods": ["شادمان"]}

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]:
        return [0.0] * 8


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        assert block.startswith("data: ")
        events.append(json.loads(block[len("data: ") :]))
    return events


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


# --- POST /api/v1/search ---


async def test_search_classic_mode_returns_tiered_results(client):
    response = await client.post("/api/v1/search", json={"mode": "classic", "page_size": 10})
    assert response.status_code == 200

    body = response.json()
    assert set(body.keys()) == {"natural_language_summary", "tier_1_results", "tier_2_results", "total_count"}
    assert body["natural_language_summary"]
    assert body["total_count"] >= 0
    assert len(body["tier_1_results"]) + len(body["tier_2_results"]) <= 10

    for result in body["tier_1_results"] + body["tier_2_results"]:
        assert result["tier"] in (1, 2)
        assert 0.0 <= result["utility_score"] <= 1.0


async def test_search_elevator_requirement_is_enforced_above_ground_floor(client):
    response = await client.post(
        "/api/v1/search", json={"mode": "classic", "requires_elevator": True, "page_size": 50}
    )
    assert response.status_code == 200
    body = response.json()
    for result in body["tier_1_results"] + body["tier_2_results"]:
        if result["floor"] > 1:
            assert result["has_elevator"] is True


async def test_search_neighborhood_filter_restricts_results(client):
    response = await client.post(
        "/api/v1/search", json={"mode": "classic", "neighborhoods": ["سعادت‌آباد"], "page_size": 50}
    )
    assert response.status_code == 200
    body = response.json()
    for result in body["tier_1_results"] + body["tier_2_results"]:
        assert result["neighborhood"] == "سعادت‌آباد"


async def test_search_intelligent_mode_without_api_key_returns_503(client):
    response = await client.post(
        "/api/v1/search", json={"mode": "intelligent", "query_text": "آپارتمان نزدیک مترو با آسانسور"}
    )
    assert response.status_code == 503


async def test_search_pagination_limits_page_size(client):
    response = await client.post("/api/v1/search", json={"mode": "classic", "page": 1, "page_size": 3})
    assert response.status_code == 200
    body = response.json()
    assert len(body["tier_1_results"]) + len(body["tier_2_results"]) <= 3


# --- POST /api/v1/chat/stream ---


async def test_chat_stream_without_api_key_returns_503(client):
    response = await client.post("/api/v1/chat/stream", json={"message": "سلام"})
    assert response.status_code == 503


async def test_chat_stream_yields_tokens_then_state_update_then_done(client):
    app.dependency_overrides[get_llm_client] = lambda: FakeChatClient()
    try:
        response = await client.post("/api/v1/chat/stream", json={"message": "ودیعه تا ۳۰۰ تومن با آسانسور"})
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    events = _parse_sse(response.text)

    token_events = [e for e in events if e["event"] == "token"]
    assert [e["content"] for e in token_events] == ["سلام", "! چند مورد پیدا کردم."]

    assert events[-2]["event"] == "state_update"
    assert events[-2]["extracted_intent"] == {
        "max_rent": 15_000_000,
        "must_have_elevator": True,
        "target_neighborhoods": ["شادمان"],
    }
    assert events[-1] == {"event": "done"}


# --- GET /api/v1/listings/{id} ---


async def test_get_listing_returns_seeded_listing(client):
    response = await client.get("/api/v1/listings/teh-1000")
    assert response.status_code == 200
    assert response.json()["id"] == "teh-1000"


async def test_get_listing_not_found_returns_404(client):
    response = await client.get("/api/v1/listings/teh-does-not-exist")
    assert response.status_code == 404


# --- GET /api/v1/transit/stations ---


async def test_get_transit_stations_returns_station_list(client):
    response = await client.get("/api/v1/transit/stations")
    assert response.status_code == 200
    stations = response.json()
    assert len(stations) > 0
    assert {"id", "name", "lat", "lon", "lines", "type", "has_elevator", "relations"} <= stations[0].keys()
