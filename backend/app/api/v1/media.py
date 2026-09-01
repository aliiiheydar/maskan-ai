"""GET /api/v1/media/image -- a narrow read-through proxy for listing photos.

We hold Divar's CDN URLs but none of the images: re-hosting 6,000 listings'
worth of photos means tens of thousands of requests against a rate-limited
origin, which is a separate project. Until that exists the browser has to load
them from ``*.divarcdn.com``, and going through the backend rather than
straight from the page buys three things:

* one place to add caching, and later to swap in our own object store without
  the frontend changing a single URL;
* immunity to whatever the CDN decides about ``Referer`` or CORS, which a
  direct ``<img>`` from localhost cannot control;
* a failure that is ours to shape -- a broken photo becomes a placeholder in
  the UI rather than a browser-rendered broken-image icon.

The host allowlist is the security boundary. Without it this endpoint would be
an open forwarder: anything on the internet, including services reachable only
from inside this network, fetchable through our origin.
"""

from __future__ import annotations

import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter()

# Divar serves photos from several hosts under one domain (s100.divarcdn.com,
# postimage01.divarcdn.com, ...), so the allowlist is the *domain*, anchored so
# that a lookalike like "divarcdn.com.evil.test" cannot match. Nothing outside
# it is proxied.
_ALLOWED_URL = re.compile(r"^https://[a-z0-9][a-z0-9\-]*\.divarcdn\.com/[\w\-./%]+$", re.IGNORECASE)
_MAX_BYTES = 8 * 1024 * 1024
# The paths are content-addressed, so a fetched image is valid forever. A year
# of immutable caching means the browser asks once per photo, ever.
_CACHE_CONTROL = "public, max-age=31536000, immutable"

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # trust_env=False: this machine exports ALL_PROXY for other work, and
        # routing CDN images through a SOCKS proxy is both slower and a
        # dependency (socksio) this endpoint has no reason to need.
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://divar.ir/"},
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


@router.get("/media/image")
async def proxy_image(url: str = Query(..., description="Absolute https://*.divarcdn.com image URL")) -> Response:
    if not _ALLOWED_URL.match(url):
        raise HTTPException(status_code=400, detail="این نشانی تصویر پشتیبانی نمی‌شود.")

    try:
        upstream = await _get_client().get(url)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="تصویر این آگهی در دسترس نیست.") from error

    if upstream.status_code != 200:
        raise HTTPException(status_code=404, detail="تصویر این آگهی پیدا نشد.")

    content_type = upstream.headers.get("content-type", "")
    if not content_type.startswith("image/") or len(upstream.content) > _MAX_BYTES:
        raise HTTPException(status_code=415, detail="محتوای دریافتی تصویر معتبری نیست.")

    return Response(content=upstream.content, media_type=content_type, headers={"Cache-Control": _CACHE_CONTROL})
