"""parse_record: both dump shapes (spec Decision 3)."""

from __future__ import annotations

from typing import Any

from flinq.modules.dictionary.kaikki import parse_record

EN_BUILDING: dict[str, Any] = {
    "word": "building",
    "lang_code": "en",
    "pos": "noun",
    "senses": [
        {
            "glosses": ["A structure built for habitation or use"],
            "examples": [{"text": "The building has three floors."}],
        }
    ],
    "translations": [
        {"code": "ru", "word": "здание", "sense": "structure"},
        {"code": "pt", "word": "edifício"},
        {"code": "de", "word": "Gebäude"},
    ],
}

RU_DOM: dict[str, Any] = {
    "word": "дом",
    "lang_code": "ru",
    "pos": "noun",
    "senses": [
        {"glosses": ["house", "building"]},
        {
            "glosses": ["home"],
            "examples": [{"text": "Я иду домой.", "english": "I am going home."}],
        },
    ],
}


def test_en_record_takes_translations_for_target() -> None:
    entry = parse_record(EN_BUILDING, source_lang="en", target_lang="ru")
    assert entry is not None
    assert entry.headword == "building"
    assert entry.entry_key == "building:noun:0"
    assert [t.translation_text for t in entry.translations] == ["здание"]
    assert entry.translations[0].usage_note == "structure"
    assert entry.examples[0].example_text == "The building has three floors."


def test_en_record_other_target_language() -> None:
    entry = parse_record(EN_BUILDING, source_lang="en", target_lang="pt")
    assert entry is not None
    assert [t.translation_text for t in entry.translations] == ["edifício"]


def test_foreign_record_takes_glosses_per_sense() -> None:
    entry = parse_record(RU_DOM, source_lang="ru", target_lang="en")
    assert entry is not None
    texts = [(t.sense_index, t.translation_text) for t in entry.translations]
    assert texts == [(0, "house; building"), (1, "home")]
    assert entry.examples == (
        type(entry.examples[0])(
            sense_index=1,
            example_text="Я иду домой.",
            example_translation="I am going home.",
        ),
    )


def test_wrong_language_is_skipped() -> None:
    assert parse_record(RU_DOM, source_lang="pt", target_lang="ru") is None


def test_record_without_translations_is_skipped() -> None:
    record: dict[str, Any] = {"word": "aaa", "lang_code": "en", "pos": "noun", "senses": []}
    assert parse_record(record, source_lang="en", target_lang="ru") is None


def test_examples_capped_at_five() -> None:
    record: dict[str, Any] = {
        "word": "casa",
        "lang_code": "pt",
        "pos": "noun",
        "senses": [{"glosses": ["дом"], "examples": [{"text": f"ex {i}"} for i in range(10)]}],
    }
    entry = parse_record(record, source_lang="pt", target_lang="ru")
    assert entry is not None
    assert len(entry.examples) == 5
