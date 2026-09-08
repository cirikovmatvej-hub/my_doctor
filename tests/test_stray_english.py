"""
Regression tests for _contains_stray_english's Roman-numeral exemption:
Russian medical staging/grading routinely keeps Roman numerals as-is ("ожог
III степени", "гипертония II-III стадии"), and the plain
r"\\b[a-zA-Z]{3,}\\b" backstop used to flag those as stray English and waste
a rewrite round-trip on the model for text that was already correct.
"""
from ai.assistant import _contains_stray_english


def test_roman_numeral_staging_is_not_flagged():
    for text in (
        "ожог III степени, нужно к врачу",
        "гипертония II-III стадии требует контроля",
        "стадия IV — направляю к онкологу",
        "хроническая болезнь почек стадии III",
    ):
        assert not _contains_stray_english(text), text


def test_actual_stray_english_is_still_flagged():
    for text in (
        "In the meantime постарайтесь отдыхать",
        "Please обратитесь к врачу",
        "Возможно, это magnesium deficiency",
    ):
        assert _contains_stray_english(text), text


def test_lowercase_roman_looking_word_is_still_flagged():
    # "civil" lowercase isn't staging notation — must not be exempted just
    # because its letters happen to overlap the Roman numeral alphabet.
    assert _contains_stray_english("civil war")
