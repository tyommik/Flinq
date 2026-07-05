"""Sentence-translation prompt: deterministic bytes (spec API-6, Task 6)."""

from __future__ import annotations

from flinq.modules.ai_translation.prompts import build_sentence_prompt


def test_prompt_is_deterministic() -> None:
    sentence = "O edifício antigo fica na praça."
    a = build_sentence_prompt(sentence_text=sentence, target_language_code="ru")
    b = build_sentence_prompt(sentence_text=sentence, target_language_code="ru")
    assert a == b


def test_prompt_contains_normalized_sentence_and_target_name() -> None:
    system, user = build_sentence_prompt(
        sentence_text="  See \n you\t later!  ", target_language_code="ru"
    )
    assert "Reply with the translation of the given sentence only" in system
    assert "Sentence: See you later!" in user
    assert "into Russian" in user


def test_prompt_whitespace_collapsed() -> None:
    a = build_sentence_prompt(sentence_text="See you later!", target_language_code="pt")
    b = build_sentence_prompt(sentence_text="See  you   later!", target_language_code="pt")
    assert a == b
    _, user = a
    assert "Sentence: See you later!" in user
    assert "into Portuguese" in user
