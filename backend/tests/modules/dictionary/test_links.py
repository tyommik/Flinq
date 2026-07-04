"""External link templates: pair filtering + URL encoding (spec Decision 7)."""

from __future__ import annotations

from flinq.modules.dictionary.links import ExternalLink, render_external_links


def _names(links: list[ExternalLink]) -> set[str]:
    return {link.name for link in links}


def test_en_ru_includes_lingvo_and_urban_and_google() -> None:
    links = render_external_links("building", "en", "ru")
    names = _names(links)
    assert {"Lingvo Live", "Google Translate", "Wiktionary", "Urban Dictionary"} <= names
    assert "WordReference" not in names  # no en-ru on WordReference


def test_pt_ru_has_no_urban() -> None:
    names = _names(render_external_links("edifício", "pt", "ru"))
    assert "Urban Dictionary" not in names


def test_text_is_url_encoded() -> None:
    [lingvo] = [
        link
        for link in render_external_links("Что такое", "ru", "en")
        if link.name == "Lingvo Live"
    ]
    assert (
        lingvo.url
        == "https://www.lingvolive.com/en-us/translate/ru-en/%D0%A7%D1%82%D0%BE%20%D1%82%D0%B0%D0%BA%D0%BE%D0%B5"
    )
