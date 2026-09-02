"""Async OpenAI-compatible client: chat completions and text embeddings.

Both capabilities are served by the single OPENROUTER_* account (see
app.core.config). A second chat provider used to sit in front of this one with
an automatic fallback; it was removed, because it ran a content filter that
rejected any message containing five or more non-ASCII characters -- which is
every Persian turn this product makes -- so the fallback fired on literally
every call.

When no real API key is configured, generate_embedding() falls back to a local
deterministic mock embedding (scikit-learn's hashing-trick vectorizer) so the
rest of the app -- and the test suite -- can run fully offline.
"""

import asyncio
import hashlib
import json
import os
from typing import Any, Optional

import httpx
from sklearn.feature_extraction.text import HashingVectorizer

from app.core import paths
from app.core.config import settings

_PLACEHOLDER_API_KEYS = {"", "your_openrouter_api_key_here"}

# Retried, with backoff: 429 is a rate limit and 5xx is a transient upstream
# fault, and both are routinely served on the next attempt.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.0

class LLMUnavailableError(RuntimeError):
    """The chat model could not be reached.

    Carries a Persian, user-facing message: the API layer surfaces it
    verbatim, so a provider outage reads as a sentence rather than as a bare
    "network error".
    """

    def __init__(self, persian_message: str, detail: str = "") -> None:
        super().__init__(detail or persian_message)
        self.persian_message = persian_message
        self.detail = detail


_UNAVAILABLE_MESSAGE = (
    "دستیار گفت‌وگو در حال حاضر در دسترس نیست. لطفاً چند لحظه دیگر دوباره تلاش کنید "
    "یا از پنل جستجو و رتبه‌بندی استفاده کنید."
)

_MOCK_EMBEDDING_DIM = 256
_mock_vectorizer = HashingVectorizer(n_features=_MOCK_EMBEDDING_DIM, alternate_sign=False, norm="l2")


def _describe_http_error(error: httpx.HTTPError) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"{error.response.status_code}: {str(error)[:200]}"
    return f"{type(error).__name__}: {error}"


def _strip_json_fence(content: str) -> str:
    """Unwrap a ```json ... ``` fence if the model emitted one."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    body = text.split("\n", 1)[1] if "\n" in text else ""
    return body.rsplit("```", 1)[0].strip()


def _mock_embedding(text: str) -> list[float]:
    """Deterministic local stand-in for a real embedding API, via the hashing
    trick (no training/corpus needed). L2-normalized, so cosine similarity
    between two mock embeddings reduces to a plain dot product."""
    vector = _mock_vectorizer.transform([text])
    return vector.toarray()[0].tolist()


# Embeddings are billed per call but are pure functions of (model, text), and
# the synthetic corpus re-embeds the same few hundred descriptions on every
# reload. Persisting them turns that into a one-time cost.
_EMBEDDING_CACHE_PATH = paths.asset("embedding_cache.json")
_embedding_cache: Optional[dict[str, list[float]]] = None
_embedding_cache_dirty = False


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha1(f"{model}\x00{text}".encode("utf-8")).hexdigest()


def _load_embedding_cache() -> dict[str, list[float]]:
    global _embedding_cache
    if _embedding_cache is None:
        try:
            _embedding_cache = json.loads(_EMBEDDING_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _embedding_cache = {}
    return _embedding_cache


def flush_embedding_cache() -> None:
    """Persist newly computed embeddings. Written atomically so an interrupted
    run can never leave a half-written cache behind."""
    global _embedding_cache_dirty
    if not _embedding_cache_dirty or _embedding_cache is None:
        return
    tmp = _EMBEDDING_CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_embedding_cache), encoding="utf-8")
    os.replace(tmp, _EMBEDDING_CACHE_PATH)
    _embedding_cache_dirty = False


class OpenRouterClient:
    """Thin async wrapper around the OpenRouter chat-completions and
    embeddings endpoints."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        # An explicit api_key/base_url is what the tests and one-off scripts
        # pass; otherwise the configured provider serves both capabilities.
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._base_url = (base_url or settings.openrouter_base_url).rstrip("/")

        # trust_env=False: this machine exports ALL_PROXY=socks://... for a VPN
        # and httpx rejects that scheme outright at construction time.
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60.0, trust_env=False)

    def has_real_api_key(self) -> bool:
        """Whether chat completions can actually be made (the embedding path
        has its own offline fallback and never needs this)."""
        return self._api_key not in _PLACEHOLDER_API_KEYS

    def has_real_embedding_key(self) -> bool:
        return self.has_real_api_key()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def _post_with_retry(
        self,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """POST a completion, retrying the failures that are worth retrying.

        A 429 or a 5xx is the provider saying "not right now", not "never":
        several chat turns in flight at once (or an eval sweep) hit the rate
        limit routinely, and giving up on the first one drops a request the
        provider would have served a second later. Backoff is short and
        bounded -- a user is waiting on the other end -- and every other status
        raises immediately, since retrying a 400 or a 401 only wastes time.
        """
        delay = _RETRY_BASE_DELAY_SECONDS
        for attempt in range(_RETRY_ATTEMPTS):
            last = attempt == _RETRY_ATTEMPTS - 1
            try:
                response = await self._client.post("/chat/completions", json=payload, headers=self._headers())
            except (httpx.TimeoutException, httpx.ConnectError):
                # A timed-out or dropped connection is the same kind of "not
                # right now" as a 429, and the only alternative here is to fail
                # the user's turn outright.
                if last:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if response.status_code in _RETRYABLE_STATUSES and not last:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = True,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Call the chat-completions endpoint. If json_mode, the assistant's
        reply is parsed as JSON and returned directly as a dict; otherwise
        the raw text reply is returned as {"content": text}."""
        payload: dict[str, Any] = {"model": model or settings.llm_model, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = await self._post_with_retry(payload)
        except httpx.HTTPError as error:
            raise LLMUnavailableError(_UNAVAILABLE_MESSAGE, _describe_http_error(error)) from error

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            # A 200 carrying an error envelope instead of a completion -- some
            # providers report an upstream failure in-band. Reported as an
            # outage rather than escaping as a bare KeyError from a caller's
            # perspective.
            raise LLMUnavailableError(
                _UNAVAILABLE_MESSAGE, f"malformed completion body: {response.text[:200]}"
            ) from error

        if not json_mode:
            return {"content": content}
        # Reasoning models occasionally wrap the object in a ```json fence
        # even under response_format=json_object, which json.loads rejects.
        return json.loads(_strip_json_fence(content))

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
        emitted = False
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    # The body has to be read explicitly on a streaming
                    # response before it can be reported.
                    detail = (await response.aread()).decode("utf-8", "replace")[:300]
                    raise httpx.HTTPStatusError(detail, request=response.request, response=response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                    if delta:
                        emitted = True
                        yield delta
        except httpx.HTTPError as error:
            if emitted:
                # Half a reply already reached the user; raising now would tear
                # the stream down mid-sentence with text already on screen.
                return
            raise LLMUnavailableError(_UNAVAILABLE_MESSAGE, _describe_http_error(error)) from error

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]:
        """Return a dense embedding for text. Falls back to a local mock
        embedding when no real OpenRouter API key is configured."""
        if not self.has_real_embedding_key():
            return _mock_embedding(text)

        global _embedding_cache_dirty
        embedding_model = model or settings.embedding_model
        cache = _load_embedding_cache()
        key = _cache_key(embedding_model, text)
        if key in cache:
            return cache[key]

        payload = {"model": embedding_model, "input": text}
        response = await self._client.post("/embeddings", json=payload, headers=self._headers())
        response.raise_for_status()
        vector = response.json()["data"][0]["embedding"]
        # Six decimals is well inside the noise floor of a unit-norm embedding
        # and roughly halves the cache file.
        cache[key] = [round(value, 6) for value in vector]
        _embedding_cache_dirty = True
        return cache[key]

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenRouterClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
