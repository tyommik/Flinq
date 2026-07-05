"""Prompt build/parse: deterministic bytes, LingQ-style hint parsing (spec Decisions 1-2)."""

from __future__ import annotations

from flinq.modules.ai_translation.prompts import (
    build_hints_prompt,
    normalize_ai_text,
    parse_hints,
)


def test_normalize_collapses_whitespace_and_nfc() -> None:
    assert normalize_ai_text("  See \n you\t later!  ") == "See you later!"
    decomposed = "é"  # e + COMBINING ACUTE ACCENT (2 codepoints)
    assert len(decomposed) == 2  # guard: literal must stay decomposed
    assert normalize_ai_text(decomposed) == "é"


def test_prompt_is_deterministic_and_contains_parts() -> None:
    a = build_hints_prompt(
        surface_text="later", context_text="See you later!", target_language_code="ru"
    )
    b = build_hints_prompt(
        surface_text=" later ", context_text="See  you later!", target_language_code="ru"
    )
    assert a == b  # normalization makes trivial client differences irrelevant
    system, user = a
    assert "1 to 3 short translation variants" in system
    assert "best first" in system
    assert "one per line" in system
    assert "Sentence: See you later!" in user
    assert "Word or phrase: later" in user
    assert "into Russian" in user


def test_parse_hints_plain_lines() -> None:
    assert parse_hints("позже\nпотом\n") == ["позже", "потом"]  # noqa: RUF001


def test_parse_hints_strips_numbering_bullets_quotes() -> None:
    text = '1. «позже»\n- "потом"\n* спустя\n'
    assert parse_hints(text) == ["позже", "потом", "спустя"]


def test_parse_hints_dedupes_and_caps_at_three() -> None:
    text = "позже\nпозже\nпотом\nспустя\nпозднее\n"  # noqa: RUF001
    assert parse_hints(text) == ["позже", "потом", "спустя"]


def test_parse_hints_empty_and_garbage() -> None:
    assert parse_hints("") == []
    assert parse_hints("\n \n- \n") == []


def test_parse_hints_keeps_word_initial_hyphen() -> None:
    assert parse_hints("-immediate\n-abrupt\n") == ["-immediate", "-abrupt"]


def test_parse_hints_strips_spaced_dash_bullets() -> None:
    assert parse_hints("- позже\n- потом\n") == ["позже", "потом"]
