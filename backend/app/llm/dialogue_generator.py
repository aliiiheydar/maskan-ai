"""Generates Persian natural-language dialogue: brief empathetic summaries of
why the Tier 1 listings were chosen (see docs/API_SPEC.md's
natural_language_summary field), and streamed conversational chat replies.
"""

from typing import Any, AsyncIterator, Optional, Protocol

from app.core.models import ExtractedSearchIntent
from app.core.normalizers import clean_for_llm, to_persian_digits
from app.core.pricing import calculate_effective_monthly_cost
from app.search.scoring import ScoredListing

SUMMARY_SYSTEM_PROMPT = """You are the voice of a friendly Persian-speaking Tehran real-estate \
assistant. Given a short list of matched apartment listings and what the user asked for, \
write ONE brief, warm, natural Persian message (1-2 sentences) explaining why these were \
picked, grounded ONLY in the numbers given -- count of results, budget fit, metro/commute \
proximity. Be polite, concise, and never robotic; no markdown, no bullet points, output \
the Persian sentence(s) only."""

CHAT_SYSTEM_PROMPT = """You are a warm, concise Persian-speaking real-estate assistant for a \
Tehran rental-search platform. Chat naturally with the user to understand what kind of home \
they want (budget, neighborhood, commute, must-haves). Keep replies short (1-3 sentences), \
polite, and always in Persian. Never use markdown."""

NO_RESULTS_MESSAGE = (
    "متأسفانه با معیارهای فعلی شما مورد کاملاً مناسبی پیدا نشد. "
    "اگر بودجه یا محدوده جستجو را کمی انعطاف‌پذیرتر کنید، حتماً گزینه‌های بهتری پیدا می‌کنیم."
)


class ChatCompletionClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    chat_completion/stream_chat_completion method set -- lets tests pass a
    lightweight fake."""

    async def chat_completion(
        self, messages: list[dict[str, str]], json_mode: bool = True, model: Optional[str] = None
    ) -> dict[str, Any]: ...

    def stream_chat_completion(
        self, messages: list[dict[str, str]], model: Optional[str] = None
    ) -> AsyncIterator[str]: ...


def _describe(scored: ScoredListing) -> str:
    cost = calculate_effective_monthly_cost(scored.listing.deposit_toman, scored.listing.rent_toman)
    return (
        f"- {scored.listing.title} | محله: {scored.listing.neighborhood} | "
        f"هزینه مؤثر ماهانه: {cost:,} تومان | فاصله تا مترو: {scored.listing.metro_walk_mins:.1f} دقیقه | "
        f"امتیاز تطابق: {scored.utility_score:.2f}"
    )


def _template_summary(tier1_results: list[ScoredListing]) -> str:
    """Deterministic, non-LLM summary used when no real OpenRouter API key is
    configured, so /search stays fully usable offline."""
    best = max(tier1_results, key=lambda s: s.utility_score)
    count = to_persian_digits(len(tier1_results))
    walk_mins = to_persian_digits(round(best.listing.metro_walk_mins))
    return (
        f"{count} مورد مناسب پیدا شد که در محدوده بودجه شما هستند؛ بهترین گزینه در "
        f"{best.listing.neighborhood} با {walk_mins} دقیقه پیاده تا مترو."
    )


async def generate_summary(
    client: ChatCompletionClient,
    tier1_results: list[ScoredListing],
    intent: ExtractedSearchIntent,
) -> str:
    """Return a short Persian natural-language summary of the Tier 1 picks."""
    if not tier1_results:
        return NO_RESULTS_MESSAGE

    if not getattr(client, "has_real_api_key", lambda: True)():
        return _template_summary(tier1_results)

    listings_block = "\n".join(_describe(s) for s in tier1_results)
    user_message = f"تعداد موارد یافت‌شده: {len(tier1_results)}\n{listings_block}"

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    result = await client.chat_completion(messages, json_mode=False)
    return result["content"].strip()


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
