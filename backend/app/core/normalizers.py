"""Persian text and digit normalization utilities."""

import re

# Common misspellings/renderings to canonicalize, matched as whole words only.
# e.g. "یوسف اباد" (bare alef) is a very common typing of "یوسف‌آباد" (alef-madda).
COMMON_SPELLING_FIXES: dict[str, str] = {
    "اباد": "آباد",
}

# Arabic-script characters that should be normalized to their Persian equivalents.
_ARABIC_TO_PERSIAN = {
    "ي": "ی",  # ي (Arabic Yeh) -> ی (Persian Yeh)
    "ك": "ک",  # ك (Arabic Kaf) -> ک (Persian Keheh)
}

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"
_DIGIT_TABLE = str.maketrans(
    _PERSIAN_DIGITS + _ARABIC_INDIC_DIGITS,
    _ASCII_DIGITS + _ASCII_DIGITS,
)


def normalize_persian_text(text: str) -> str:
    """Normalize Arabic Yeh/Kaf to Persian, collapse whitespace, and fix common
    whole-word misspellings (e.g. "اباد" -> "آباد")."""
    for arabic_ch, persian_ch in _ARABIC_TO_PERSIAN.items():
        text = text.replace(arabic_ch, persian_ch)

    text = re.sub(r"\s+", " ", text).strip()

    for wrong, correct in COMMON_SPELLING_FIXES.items():
        # Bounded by whitespace/string edges rather than \b, which is unreliable
        # around Persian joiners/ZWNJ.
        text = re.sub(rf"(?<!\S){re.escape(wrong)}(?!\S)", correct, text)

    return text


def parse_persian_numbers(text: str) -> str:
    """Convert Persian and Arabic-Indic digits to ASCII digits."""
    return text.translate(_DIGIT_TABLE)
