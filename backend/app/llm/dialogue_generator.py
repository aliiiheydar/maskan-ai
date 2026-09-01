"""Generates the Persian conversational reply for one chat turn.

This module used to also write the `natural_language_summary` shown above the
feed. That was removed: the sentence repeated what the cards already say, cost
a chat round-trip on every keystroke-debounced search, and held the results
behind a generation nobody asked for. `/search` now builds that line itself
(see app.api.v1.search), so the only prose left here is the chat itself.
"""

from typing import AsyncIterator, Optional, Protocol

from app.core.normalizers import clean_for_llm

CHAT_SYSTEM_PROMPT = """You are a warm, concise Persian-speaking real-estate assistant for a \
Tehran rental-search platform. Chat naturally with the user to understand what kind of home \
they want (budget, neighborhood, commute, must-haves). Keep replies short (1-3 sentences), \
polite, and always in Persian. Never use markdown.

The search itself runs beside you: the filters are extracted from this same conversation and \
the results appear next to the chat. So your reply confirms what you understood and asks for \
what is missing -- it never lists homes, quotes prices, or claims to have found anything.

- Say back only what the user actually said. Do not add a preference they did not state: \
someone who says they would rather pay less has NOT asked to swap rent for deposit, and \
offering them a تبدیل ("رهن کمتر و اجاره بیشتر") reads as though you misheard them. Only \
discuss a تبدیل if they raised it.
- Do not promise anything about the results ("حتما نزدیک مترو پیدا می‌کنم") -- you have not \
seen them.
- When the message is too thin to search on, ask for the ONE detail that would help most \
(usually budget, area, or size), in a single question.
- Do not restate every constraint back as a list. One natural sentence that shows you \
understood, and then the question if there is one.
"""


class ChatCompletionClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    stream_chat_completion -- lets tests pass a lightweight fake."""

    def stream_chat_completion(
        self, messages: list[dict[str, str]], model: Optional[str] = None
    ) -> AsyncIterator[str]: ...


async def stream_chat_reply(
    client: ChatCompletionClient,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
) -> AsyncIterator[str]:
    """Stream a conversational Persian reply token-by-token."""
    messages: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in history or []:
        messages.append({"role": turn["role"], "content": clean_for_llm(turn["content"])})
    messages.append({"role": "user", "content": clean_for_llm(message)})

    async for token in client.stream_chat_completion(messages):
        yield token
