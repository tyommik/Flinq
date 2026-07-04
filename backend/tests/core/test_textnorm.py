"""Canonical normalization: the token<->dictionary join key (ADR-0001 + FLQ-1 follow-up)."""

# ruff: noqa: RUF001 -- RIGHT SINGLE QUOTATION MARK (U+2019) literals are the point of this file.

from __future__ import annotations

from flinq.core.textnorm import normalize_token


def test_lowercases_and_strips_outer_punctuation() -> None:
    assert normalize_token("«Hello!»") == "hello"


def test_casefold_beats_lower() -> None:
    # .lower() keeps "ß"; .casefold() folds it — the whole point of the fix.
    assert normalize_token("Straße") == "strasse"


def test_curly_apostrophe_joins_with_ascii() -> None:
    curly = "d’água"  # RIGHT SINGLE QUOTATION MARK
    assert normalize_token(curly) == normalize_token("d'água") == "d'água"


def test_curly_apostrophe_literal_is_really_u2019() -> None:
    assert "’" != "'"  # sanity: the two test inputs differ before normalization
    assert normalize_token("’x’") == "x"


def test_keeps_diacritics_and_internal_hyphen() -> None:
    assert normalize_token("Está-se") == "está-se"
    assert normalize_token("Ёлка") == "ёлка"


def test_tokenizer_uses_shared_function() -> None:
    from flinq.modules.lesson_library.tokenization import tokenize

    [tok] = [t for t in tokenize("Straße.") if t.is_word_like]
    assert tok.normalized_text == "strasse"
