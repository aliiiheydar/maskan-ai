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
_REVERSE_DIGIT_TABLE = str.maketrans(_ASCII_DIGITS, _PERSIAN_DIGITS)


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


def to_persian_digits(value: "int | str") -> str:
    """Convert ASCII digits to Persian digits, for user-facing display text."""
    return str(value).translate(_REVERSE_DIGIT_TABLE)


def clean_for_llm(text: str) -> str:
    """Full normalization pipeline (char normalization, then digit conversion)
    applied to any Persian text before it is sent to an LLM."""
    return parse_persian_numbers(normalize_persian_text(text))


# --- name matching ---------------------------------------------------------
#
# Place names are matched, not displayed, in a deliberately lossy form: users
# type "یوسف آباد" for "یوسف‌آباد" and "تاتر شهر" for "تئاتر شهر", and neither
# should miss. Diacritics carry no meaning here, the hamza carriers are typed
# inconsistently, and ZWNJ is a word-internal break people write as a space or
# as nothing at all.
_DIACRITICS = re.compile(r"[ً-ْٰ]")
_ZWNJ = re.compile(r"[​-‏]")
_HAMZA_FORMS = {"آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا", "ئ": "ی", "ؤ": "و", "ء": "", "ة": "ه", "ۀ": "ه"}


def normalize_for_match(text: str) -> str:
    """Persian text reduced to the form two spellings of one name share."""
    cleaned = _ZWNJ.sub(" ", _DIACRITICS.sub("", text or ""))
    for form, plain in _HAMZA_FORMS.items():
        cleaned = cleaned.replace(form, plain)
    return re.sub(r"\s+", " ", normalize_persian_text(cleaned)).strip()


def squash_for_match(text: str) -> str:
    """`normalize_for_match` with spacing removed entirely -- the form in which
    "یوسف آباد" and "یوسف‌آباد" finally compare equal."""
    return normalize_for_match(text).replace(" ", "")
