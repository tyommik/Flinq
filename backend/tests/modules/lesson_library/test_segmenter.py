"""Unit tests for sentence/paragraph segmentation (AC#2). No DB."""

from __future__ import annotations

from flinq.modules.lesson_library.tokenization import RegexSegmenter, Span


def _texts(spans: list[Span]) -> list[str]:
    return [s.text for s in spans]


def test_paragraphs_split_on_blank_lines() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_paragraphs("First para.\n\nSecond para.")
    assert _texts(spans) == ["First para.", "Second para."]


def test_paragraph_offsets_index_back_into_source() -> None:
    seg = RegexSegmenter("en")
    src = "First para.\n\nSecond para."
    spans = seg.split_paragraphs(src)
    for s in spans:
        assert src[s.start : s.end] == s.text


def test_english_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_sentences("Mr. Smith left. He waved.")
    assert _texts(spans) == ["Mr. Smith left.", "He waved."]


def test_english_decimal_does_not_split() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_sentences("Pi is 3.14 today. Yes.")
    assert _texts(spans) == ["Pi is 3.14 today.", "Yes."]


def test_russian_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("ru")
    spans = seg.split_sentences("Купи хлеб, молоко и т.д. Потом приходи.")
    assert _texts(spans) == ["Купи хлеб, молоко и т.д.", "Потом приходи."]


def test_portuguese_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("pt")
    spans = seg.split_sentences("A Dr.ª Ana chegou. Ela sorriu.")
    assert _texts(spans) == ["A Dr.ª Ana chegou.", "Ela sorriu."]


def test_initials_do_not_split() -> None:
    seg = RegexSegmenter("ru")
    spans = seg.split_sentences("Пришёл А. С. Пушкин.")
    assert len(spans) == 1


def test_sentence_offsets_index_back_into_source() -> None:
    seg = RegexSegmenter("en")
    src = "One. Two."
    spans = seg.split_sentences(src)
    for s in spans:
        assert src[s.start : s.end] == s.text
