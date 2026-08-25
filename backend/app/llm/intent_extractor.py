"""Extracts a structured ExtractedSearchIntent from a Persian chat message."""

from typing import Any, Optional, Protocol

from app.core.models import ExtractedSearchIntent
from app.core.normalizers import clean_for_llm

SYSTEM_PROMPT = """You are the intent-extraction engine for a Tehran (Iran) rental-housing \
search platform. Read a Persian conversational message from a home-seeker (and any prior \
turns) and output ONE JSON object matching the schema below. Output the JSON object only \
-- no commentary, no markdown fences.

## Iranian rental colloquialisms you MUST handle correctly
- "پیش", "رهن", "ودیعه" all refer to the up-front deposit -> max_deposit.
- "اجاره" refers to the monthly rent -> max_rent.
- "تبدیل" means the tenant is open to converting between deposit and rent \
(can_convert = true). Default can_convert to true unless the user explicitly refuses \
conversion (e.g. "بدون تبدیل", "تبدیل نمی‌خوام").
- Iranians almost always state deposit/rent figures in **million Tomans** in casual \
speech: "۲۰۰ پیش" = 200000000 Toman deposit, "۱۵ تومن اجاره" = 15000000 Toman rent, \
"۳۰۰ ودیعه" = 300000000 Toman. Multiply a bare number under ~1000 by 1,000,000 to get \
Tomans, UNLESS it already has 7+ digits or the user says "میلیون" / "هزار تومان" \
explicitly.
- "متری" / "متر" after a number is area_sqm (e.g. "۸۰ متری" -> min_area_sqm: 80).
- "خواب" / "اتاق خواب" after a number is min_rooms.
- "آسانسور" -> must_have_elevator; "پارکینگ" -> must_have_parking.

## Output schema
{
  "max_deposit": int | null,
  "max_rent": int | null,
  "can_convert": bool,
  "min_area_sqm": int | null,
  "min_rooms": int | null,
  "must_have_elevator": bool,
  "must_have_parking": bool,
  "target_neighborhoods": [string, ...],
  "workplace_lat": float | null,
  "workplace_lon": float | null,
  "workplace_name": string | null,
  "max_commute_mins": int,
  "soft_preferences": [string, ...],
  "soft_preference_summary": string
}

Only set a field when the conversation actually implies it; otherwise omit it (the \
caller fills in defaults). Never invent neighborhoods, coordinates, or numbers that \
were not stated or clearly implied.

## Example
User: "۲۰۰ پیش دارم ماهی ۱۵ تومن اجاره ولی تبدیل هم باشه"
Output: {"max_deposit": 200000000, "max_rent": 15000000, "can_convert": true}
"""


class ChatCompletionClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    chat_completion method -- lets tests pass a lightweight fake."""

    async def chat_completion(
        self, messages: list[dict[str, str]], json_mode: bool = True, model: Optional[str] = None
    ) -> dict[str, Any]: ...


async def extract_search_intent(
    client: ChatCompletionClient,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
) -> ExtractedSearchIntent:
    """Extract structured search intent from a Persian chat message plus
    optional prior turns (each {"role": "user"|"assistant", "content": str})."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        messages.append({"role": turn["role"], "content": clean_for_llm(turn["content"])})
    messages.append({"role": "user", "content": clean_for_llm(message)})

    raw_intent = await client.chat_completion(messages, json_mode=True)
    return ExtractedSearchIntent.model_validate(raw_intent)
