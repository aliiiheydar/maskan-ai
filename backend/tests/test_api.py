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
    assert set(body.keys()) == {
        "natural_language_summary",
        "tier_1_results",
        "tier_2_results",
        "map_points",
        "map_clusters",
        "total_count",
        "applied_intent",
    }
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
    # target_neighborhood_keys is derived, not extracted: the endpoint resolves
    # the model's Persian place names onto real neighborhood polygons before
    # emitting, so the client receives the search area already grounded.
    assert events[-2]["extracted_intent"] == {
        "max_rent": 15_000_000,
        "must_have_elevator": True,
        "target_neighborhoods": ["شادمان"],
        "target_neighborhood_keys": ["656"],
    }
    assert events[-1] == {"event": "done"}


# --- GET /api/v1/listings/{id} ---


async def test_get_listing_returns_seeded_listing(client):
    # The id is taken from a search rather than hard-coded: the corpus now comes
    # from the SQLite build of the real crawl, whose ids are Divar tokens, and a
    # checkout with no database falls back to synthetic "teh-*" ones.
    search = await client.post("/api/v1/search", json={"mode": "classic", "page_size": 1})
    listing_id = search.json()["tier_1_results"][0]["id"]

    response = await client.get(f"/api/v1/listings/{listing_id}")
    assert response.status_code == 200
    assert response.json()["id"] == listing_id


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


# --- GET /api/v1/config ---


async def test_config_reports_the_ai_search_off_without_a_key(client):
    """The suite runs on the placeholder key (see conftest), which is exactly
    the checkout this flag exists to describe."""
    body = (await client.get("/api/v1/config")).json()
    assert body["ai_search_enabled"] is False


async def test_config_reports_the_ai_search_on_with_a_key(client):
    app.dependency_overrides[get_llm_client] = lambda: FakeChatClient()
    try:
        body = (await client.get("/api/v1/config")).json()
    finally:
        app.dependency_overrides.clear()
    assert body["ai_search_enabled"] is True


async def test_config_publishes_the_explore_map_switch(client, monkeypatch):
    """The header hides کاوش نقشه on the strength of this field alone, so a
    deployment turning it off has to actually reach the client.

    Both directions are set explicitly rather than read once: whatever the
    developer happens to have in backend/.env is not what is under test."""
    from app.core.config import settings

    for configured in (True, False):
        monkeypatch.setattr(settings, "explore_map_enabled", configured)
        body = (await client.get("/api/v1/config")).json()
        assert body["explore_map_enabled"] is configured


# --- GET /api/v1/geo/* ---


async def test_list_neighborhoods_omits_the_polygons(client):
    """~700 KB of GeoJSON if it did not: the picker needs names and centres,
    and asks for shapes only for what the user selected."""
    body = (await client.get("/api/v1/geo/neighborhoods")).json()
    assert len(body) > 200
    assert "geometry" not in body[0]
    assert {"key", "title", "center_lat", "center_lon", "area_sqkm"} <= set(body[0])


async def test_neighborhood_shapes_returns_geometry_for_the_keys_asked_for(client):
    keys = [n["key"] for n in (await client.get("/api/v1/geo/neighborhoods")).json()[:3]]
    body = (await client.get("/api/v1/geo/neighborhoods/shapes", params={"keys": ",".join(keys)})).json()
    assert [shape["key"] for shape in body] == keys
    assert all(shape["geometry"]["type"] in {"Polygon", "MultiPolygon"} for shape in body)


async def test_neighborhood_shapes_refuses_an_unbounded_request(client):
    keys = ",".join(str(index) for index in range(200))
    assert (await client.get("/api/v1/geo/neighborhoods/shapes", params={"keys": keys})).status_code == 400


async def test_unknown_neighborhood_keys_are_dropped_rather_than_erroring(client):
    body = (await client.get("/api/v1/geo/neighborhoods/shapes", params={"keys": "not-a-key"})).json()
    assert body == []


async def test_search_area_dissolves_the_selection_into_one_outline(client):
    keys = [n["key"] for n in (await client.get("/api/v1/geo/neighborhoods")).json()[:4]]
    body = (await client.get("/api/v1/geo/neighborhoods/area", params={"keys": ",".join(keys)})).json()
    assert body["keys"] == keys
    assert body["geometry"]["type"] in {"Polygon", "MultiPolygon"}


async def test_search_area_of_nothing_is_no_shape_rather_than_an_error(client):
    body = (await client.get("/api/v1/geo/neighborhoods/area", params={"keys": ""})).json()
    assert body == {"keys": [], "geometry": None}


async def test_neighborhood_at_a_point_finds_the_one_containing_it(client):
    first = (await client.get("/api/v1/geo/neighborhoods")).json()[0]
    params = {"lat": first["center_lat"], "lon": first["center_lon"]}
    found = (await client.get("/api/v1/geo/neighborhood-at", params=params)).json()
    assert found is not None and found["key"] == first["key"]


async def test_a_point_outside_every_polygon_answers_none_not_an_error(client):
    """The polygons cover about two thirds of the city; a click on a park or a
    highway legitimately belongs to no محله."""
    response = await client.get("/api/v1/geo/neighborhood-at", params={"lat": 10.0, "lon": 10.0})
    assert response.status_code == 200
    assert response.json() is None


async def test_city_boundary_is_a_named_shape(client):
    body = (await client.get("/api/v1/geo/city")).json()
    assert body["name"]
    assert body["geometry"]["type"] in {"Polygon", "MultiPolygon"}


# --- GET /api/v1/transit/* ---


async def test_isochrone_returns_one_merged_shape(client):
    params = {"lat": 35.7575, "lon": 51.41, "max_minutes": 30, "mode": "transit"}
    body = (await client.get("/api/v1/transit/isochrone", params=params)).json()
    assert body["mode"] == "transit"
    assert body["geometry"]["type"] in {"Polygon", "MultiPolygon"}


async def test_isochrone_rejects_a_mode_it_cannot_draw(client):
    params = {"lat": 35.7575, "lon": 51.41, "max_minutes": 30, "mode": "teleport"}
    assert (await client.get("/api/v1/transit/isochrone", params=params)).status_code == 422


async def test_congestion_zones_come_back_labelled(client):
    body = (await client.get("/api/v1/transit/congestion-zones")).json()
    assert body
    assert all(zone["label"] and zone["geometry"]["type"] in {"Polygon", "MultiPolygon"} for zone in body)
