"""POST /api/v1/chat/stream -- SSE conversational streaming."""

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import get_llm_client
from app.api.v1.schemas import ChatStreamRequest
from app.llm.client import OpenRouterClient
from app.llm.dialogue_generator import stream_chat_reply
from app.llm.intent_extractor import extract_search_intent

router = APIRouter()


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_stream(client: OpenRouterClient, message: str, history: list[dict[str, str]]) -> AsyncIterator[str]:
    async for token in stream_chat_reply(client, message, history):
        yield _sse({"event": "token", "content": token})

    intent = await extract_search_intent(client, message, history)
    yield _sse({"event": "state_update", "extracted_intent": intent.model_dump(exclude_unset=True)})
    yield _sse({"event": "done"})


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatStreamRequest,
    client: OpenRouterClient = Depends(get_llm_client),
) -> StreamingResponse:
    if not client.has_real_api_key():
        raise HTTPException(status_code=503, detail="Chat requires an OpenRouter API key.")

    history = [turn.model_dump() for turn in payload.history]
    return StreamingResponse(_event_stream(client, payload.message, history), media_type="text/event-stream")
