"""Async OpenRouter client: chat completions and text embeddings.

When no real API key is configured, generate_embedding() falls back to a local
deterministic mock embedding (scikit-learn's hashing-trick vectorizer) so the
rest of the app -- and the test suite -- can run fully offline.
"""

import json
from typing import Any, Optional

import httpx
from sklearn.feature_extraction.text import HashingVectorizer

from app.core.config import settings

_PLACEHOLDER_API_KEYS = {"", "your_openrouter_api_key_here"}

_MOCK_EMBEDDING_DIM = 256
_mock_vectorizer = HashingVectorizer(n_features=_MOCK_EMBEDDING_DIM, alternate_sign=False, norm="l2")


def _mock_embedding(text: str) -> list[float]:
    """Deterministic local stand-in for a real embedding API, via the hashing
    trick (no training/corpus needed). L2-normalized, so cosine similarity
    between two mock embeddings reduces to a plain dot product."""
    vector = _mock_vectorizer.transform([text])
    return vector.toarray()[0].tolist()


class OpenRouterClient:
    """Thin async wrapper around the OpenRouter chat-completions and
    embeddings endpoints."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._base_url = (base_url or settings.openrouter_base_url).rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0, trust_env=False)

    def has_real_api_key(self) -> bool:
        return self._api_key not in _PLACEHOLDER_API_KEYS

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = True,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Call the chat-completions endpoint. If json_mode, the assistant's
        reply is parsed as JSON and returned directly as a dict; otherwise
        the raw text reply is returned as {"content": text}."""
        payload: dict[str, Any] = {
            "model": model or settings.llm_model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = await self._client.post("/chat/completions", json=payload, headers=self._headers())
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content) if json_mode else {"content": content}

    async def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
    ):
        """Stream the assistant's reply as it is generated, yielding each
        text delta (OpenAI-compatible SSE chunk format, as used by OpenRouter)."""
        payload: dict[str, Any] = {
            "model": model or settings.llm_model,
            "messages": messages,
            "stream": True,
        }
        async with self._client.stream("POST", "/chat/completions", json=payload, headers=self._headers()) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0]["delta"].get("content")
                if delta:
                    yield delta

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]:
        """Return a dense embedding for text. Falls back to a local mock
        embedding when no real OpenRouter API key is configured."""
        if not self.has_real_api_key():
            return _mock_embedding(text)

        payload = {"model": model or settings.embedding_model, "input": text}
        response = await self._client.post("/embeddings", json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenRouterClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
