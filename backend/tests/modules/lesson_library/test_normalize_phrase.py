"""normalize_phrase: join key фразы (ADR-0001) поверх канонического tokenize."""

from __future__ import annotations

from flinq.modules.lesson_library.tokenization import normalize_phrase


def test_joins_normalized_words_with_single_space() -> None:
    assert normalize_phrase("So Far,  so GOOD") == "so far so good"


def test_punctuation_tokens_are_dropped() -> None:
    assert normalize_phrase("wait — really?!") == "wait really"


def test_internal_apostrophe_and_hyphen_kept() -> None:
    assert normalize_phrase("a well-known fact") == "a well-known fact"
    assert normalize_phrase("don't give up") == "don't give up"


def test_curly_apostrophe_splits_word() -> None:
    # Известный квирк замороженного токенизатора (FLQ-1 follow-up): U+2019
    # не входит в internal word chars, поэтому "don't" (curly apostrophe)
    # распадается на три токена. Инвариант join-key при этом сохраняется —
    # уроки проходят через тот же tokenize(), поэтому ключи фразы/урока
    # совпадают: "don t".
    assert normalize_phrase("don’t give up") == "don t give up"  # noqa: RUF001 -- U+2019 is the point


def test_empty_and_punct_only() -> None:
    assert normalize_phrase("") == ""
    assert normalize_phrase("?! …") == ""


def test_idempotent_on_normalized_text() -> None:
    assert normalize_phrase("so far so good") == "so far so good"
