"""External dictionary link templates rendered server-side (spec Decision 7).

Constant defaults for MVP; moves to admin config in FLQ-11 without touching
the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class ExternalLink:
    name: str
    url: str


@dataclass(frozen=True)
class ExternalDictionaryTemplate:
    name: str
    url_template: str  # placeholders: {text} {from} {to}
    pairs: frozenset[tuple[str, str]] | None = None  # None = any pair


DEFAULT_EXTERNAL_DICTIONARIES: tuple[ExternalDictionaryTemplate, ...] = (
    ExternalDictionaryTemplate(
        "Lingvo Live",
        "https://www.lingvolive.com/en-us/translate/{from}-{to}/{text}",
        frozenset({("en", "ru"), ("ru", "en"), ("pt", "ru"), ("ru", "pt")}),
    ),
    ExternalDictionaryTemplate(
        "WordReference",
        "https://www.wordreference.com/{from}{to}/{text}",
        frozenset({("en", "pt"), ("pt", "en")}),
    ),
    ExternalDictionaryTemplate(
        "Google Translate", "https://translate.google.com/?sl={from}&tl={to}&text={text}"
    ),
    ExternalDictionaryTemplate("Wiktionary", "https://en.wiktionary.org/wiki/{text}"),
    ExternalDictionaryTemplate(
        "Urban Dictionary",
        "https://www.urbandictionary.com/define.php?term={text}",
        frozenset({("en", "ru"), ("en", "pt"), ("en", "en")}),
    ),
)


def render_external_links(text: str, from_lang: str, to_lang: str) -> list[ExternalLink]:
    """Substitute placeholders for every template matching the pair."""
    values = {"text": quote(text, safe=""), "from": from_lang, "to": to_lang}
    return [
        ExternalLink(name=t.name, url=t.url_template.format_map(values))
        for t in DEFAULT_EXTERNAL_DICTIONARIES
        if t.pairs is None or (from_lang, to_lang) in t.pairs
    ]
