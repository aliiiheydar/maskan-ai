from app.core.normalizers import normalize_persian_text, parse_persian_numbers


def test_normalize_and_parse_mandated_fixture():
    text = "آپارتمان در يوسف اباد با كمد ديواري و ۱۲۳ متر"
    expected = "آپارتمان در یوسف آباد با کمد دیواری و 123 متر"
    result = parse_persian_numbers(normalize_persian_text(text))
    assert result == expected


def test_parse_persian_numbers_handles_arabic_indic_digits():
    assert parse_persian_numbers("٠١٢٣٤٥٦٧٨٩") == "0123456789"


def test_parse_persian_numbers_handles_persian_digits():
    assert parse_persian_numbers("۰۱۲۳۴۵۶۷۸۹") == "0123456789"


def test_normalize_persian_text_char_substitution_without_spelling_fix():
    text = "كتاب و يخچال"
    assert normalize_persian_text(text) == "کتاب و یخچال"


def test_normalize_persian_text_does_not_rewrite_word_fragment():
    # "اباد" glued mid-word (no surrounding whitespace) must NOT be rewritten.
    text = "شهرکاباد تست"
    assert normalize_persian_text(text) == "شهرکاباد تست"


def test_normalize_persian_text_collapses_whitespace():
    text = "متن   با    فاصله  زیاد"
    assert normalize_persian_text(text) == "متن با فاصله زیاد"
