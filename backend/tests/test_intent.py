from typing import Any, Optional

from app.core.models import ExtractedSearchIntent
from app.llm.intent_extractor import extract_search_intent


class FakeClient:
    """Records the messages it was called with and returns a canned response,
    standing in for OpenRouterClient without any network access."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.last_messages: Optional[list[dict[str, str]]] = None

    async def chat_completion(
        self, messages: list[dict[str, str]], json_mode: bool = True, model: Optional[str] = None
    ) -> dict[str, Any]:
        self.last_messages = messages
        return self.response


async def test_extract_search_intent_parses_tabdil_tradeoff_example():
    fake = FakeClient({"max_deposit": 200_000_000, "max_rent": 15_000_000, "can_convert": True})
    intent = await extract_search_intent(fake, "۲۰۰ پیش دارم ماهی ۱۵ تومن اجاره ولی تبدیل هم باشه")

    assert isinstance(intent, ExtractedSearchIntent)
    assert intent.max_deposit == 200_000_000
    assert intent.max_rent == 15_000_000
    assert intent.can_convert is True


async def test_extract_search_intent_fills_defaults_for_missing_fields():
    fake = FakeClient({"max_rent": 12_000_000})
    intent = await extract_search_intent(fake, "اجاره تا ۱۲ تومن")

    assert intent.max_rent == 12_000_000
    assert intent.max_deposit is None
    assert intent.must_have_elevator is False
    assert intent.max_commute_mins == 45
    assert intent.target_neighborhoods == []


async def test_extract_search_intent_normalizes_persian_digits_and_chars_before_sending():
    fake = FakeClient({})
    await extract_search_intent(fake, "يوسف اباد ۱۲۳ متر")

    user_message = fake.last_messages[-1]["content"]
    assert user_message == "یوسف آباد 123 متر"


async def test_extract_search_intent_includes_and_normalizes_history():
    fake = FakeClient({})
    history = [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "چطور می‌تونم كمک کنم؟"},
    ]
    await extract_search_intent(fake, "۱۵۰ پیش دارم", history=history)

    assert fake.last_messages[0]["role"] == "system"
    contents = [m["content"] for m in fake.last_messages]
    assert "سلام" in contents
    assert "چطور می‌تونم کمک کنم؟" in contents  # ك normalized to ک
