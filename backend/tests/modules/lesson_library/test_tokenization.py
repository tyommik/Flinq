"""Unit tests for tokenization primitives (AC#2). No DB."""

from __future__ import annotations

from flinq.modules.lesson_library.tokenization import (
    Token,
    is_word_like,
    normalize_token,
    tokenize,
)


def test_normalize_lowercases_and_trims_outer_punctuation() -> None:
    assert normalize_token("Mundo.") == "mundo"
    assert normalize_token("«Olá»") == "olá"
    assert normalize_token("HELLO!") == "hello"


def test_normalize_preserves_diacritics() -> None:
    assert normalize_token("Não.") == "não"
    assert normalize_token("Café,") == "café"
    assert normalize_token("Что-то") == "что-то"


def test_normalize_preserves_internal_hyphen_and_apostrophe() -> None:
    assert normalize_token("co-op,") == "co-op"
    assert normalize_token("L'eau") == "l'eau"
    assert normalize_token("don't") == "don't"


def test_normalize_punctuation_only_is_empty() -> None:
    assert normalize_token("...") == ""
    assert normalize_token(",") == ""


def test_is_word_like() -> None:
    assert is_word_like("mundo") is True
    assert is_word_like("co-op") is True
    assert is_word_like("3.14") is True
    assert is_word_like(".") is False
    assert is_word_like("—") is False


def test_tokenize_splits_words_and_punctuation_with_offsets() -> None:
    tokens = tokenize("Olá mundo.")
    assert [t.surface_text for t in tokens] == ["Olá", "mundo", "."]
    assert [t.normalized_text for t in tokens] == ["olá", "mundo", ""]
    assert [t.is_word_like for t in tokens] == [True, True, False]
    first = tokens[0]
    assert "Olá mundo."[first.start_char_offset : first.end_char_offset] == "Olá"
    period = tokens[-1]
    assert "Olá mundo."[period.start_char_offset : period.end_char_offset] == "."


def test_tokenize_keeps_internal_marks_as_one_token() -> None:
    tokens = tokenize("co-op l'eau")
    assert [t.surface_text for t in tokens] == ["co-op", "l'eau"]
    assert all(isinstance(t, Token) for t in tokens)
