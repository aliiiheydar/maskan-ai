"""POST /api/v1/chat/stream -- SSE conversational streaming."""

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import get_llm_client
from app.api.v1.schemas import ChatStreamRequest
from app.llm.client import LLMUnavailableError, OpenRouterClient
from app.llm.dialogue_generator import stream_chat_reply
from app.llm.intent_extractor import extract_search_intent

router = APIRouter()

GENERIC_ERROR_MESSAGE = (
    "ارتباط با دستیار هوشمند برقرار نشد. لطفاً دوباره تلاش کنید؛ "
    "در این فاصله می‌توانید از فیلترهای کلاسیک استفاده کنید."
)
EXTRACTION_ERROR_MESSAGE = (
    "پاسخ آماده شد، اما نتوانستم فیلترها را از گفتگو استخراج کنم. "
    "لطفاً درخواستتان را کمی روشن‌تر بنویسید یا فیلترها را دستی تنظیم کنید."
)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_stream(client: OpenRouterClient, message: str, history: list[dict[str, str]]) -> AsyncIterator[str]:
    """SSE frames for one chat turn.

    Failures are reported as an `error` frame followed by `done`, never by
    tearing the connection down mid-stream: an aborted SSE body reaches the
    browser as an opaque "network error", which tells the user nothing and
    leaves the assistant bubble spinning forever.
    """
    try:
        async for token in stream_chat_reply(client, message, history):
            yield _sse({"event": "token", "content": token})
    except LLMUnavailableError as error:
        yield _sse({"event": "error", "message": error.persian_message})
        yield _sse({"event": "done"})
        return
    except Exception:
        yield _sse({"event": "error", "message": GENERIC_ERROR_MESSAGE})
        yield _sse({"event": "done"})
        return

    try:
        intent = await extract_search_intent(client, message, history)
    except Exception:
        # The reply already reached the user; only the filter extraction
        # failed, so the turn ends normally with nothing applied rather than
        # throwing away a good answer.
        yield _sse({"event": "error", "message": EXTRACTION_ERROR_MESSAGE})
        yield _sse({"event": "done"})
        return

    # target_neighborhood_keys is derived, never "set" by the model, so it has
    # to be added back explicitly alongside the exclude_unset payload.
    extracted = intent.model_dump(exclude_unset=True)
    if intent.target_neighborhood_keys:
        extracted["target_neighborhood_keys"] = intent.target_neighborhood_keys
    yield _sse({"event": "state_update", "extracted_intent": extracted})
    yield _sse({"event": "done"})


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatStreamRequest,
    client: OpenRouterClient = Depends(get_llm_client),
) -> StreamingResponse:
    if not client.has_real_api_key():
        raise HTTPException(
            status_code=503,
            detail="دستیار هوشمند پیکربندی نشده است. لطفاً از فیلترهای کلاسیک استفاده کنید.",
        )

    history = [turn.model_dump() for turn in payload.history]
    return StreamingResponse(_event_stream(client, payload.message, history), media_type="text/event-stream")
