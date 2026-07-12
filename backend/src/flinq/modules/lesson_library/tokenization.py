"""Segmentation and tokenization for lesson text (ADR-0001).

Pure functions only — no DB, no I/O. `normalize_token` is the canonical
join key shared between lesson occurrences and the future vocabulary layer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from flinq.core.textnorm import normalize_token

# A word: a run of word chars that may contain internal hyphens/apostrophes,
# OR a single word char, OR a run of punctuation (non-word, non-space).
_TOKEN_RE = re.compile(r"\w[\w''\-]*\w|\w|[^\w\s]+", re.UNICODE)
_WORD_CHAR_RE = re.compile(r"\w", re.UNICODE)


@dataclass(frozen=True)
class Token:
    surface_text: str
    normalized_text: str
    start_char_offset: int
    end_char_offset: int
    is_word_like: bool


def is_word_like(surface: str) -> bool:
    """True if the token contains at least one word character."""
    return bool(_WORD_CHAR_RE.search(unicodedata.normalize("NFC", surface)))


def tokenize(text: str, *, base_offset: int = 0) -> list[Token]:
    """Split text into word and punctuation tokens with absolute char offsets.

    `base_offset` is added to every offset so callers can tokenize a slice of a
    larger document and keep offsets relative to the whole document.
    """
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(text):
        surface = m.group(0)
        tokens.append(
            Token(
                surface_text=surface,
                normalized_text=normalize_token(surface),
                start_char_offset=base_offset + m.start(),
                end_char_offset=base_offset + m.end(),
                is_word_like=is_word_like(surface),
            )
        )
    return tokens


def normalize_phrase(surface: str) -> str:
    """Phrase join key (ADR-0001): normalized word tokens joined by single spaces.

    Uses the same tokenizer as lesson import, so the result always matches the
    `normalized_text` sequence of lesson tokens. Punctuation tokens are dropped,
    as are word-like tokens whose normalized form is empty (e.g. "_", which is
    word-like but normalizes to "") — otherwise they would inject bogus empty
    "words" into the join key.
    """
    return " ".join(
        t.normalized_text for t in tokenize(surface) if t.is_word_like and t.normalized_text
    )


# ---------------------------------------------------------------------------
# Sentence / paragraph segmentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    text: str
    start: int
    end: int


class Segmenter(Protocol):
    """Splits text into paragraphs and sentences with absolute offsets."""

    def split_paragraphs(self, text: str) -> list[Span]: ...

    def split_sentences(self, paragraph: str, *, base_offset: int = 0) -> list[Span]: ...


# Per-language abbreviations (lowercased, without the trailing period).
_ABBREVIATIONS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "mr",
            "mrs",
            "ms",
            "dr",
            "prof",
            "sr",
            "jr",
            "st",
            "vs",
            "etc",
            "inc",
            "ltd",
            "co",
            "no",
            "fig",
            "e.g",
            "i.e",
            "approx",
        }
    ),
    "ru": frozenset(
        {
            "т",
            "д",
            "п",
            "г",
            "гг",
            "стр",
            "рис",
            "см",
            "им",
            "др",
            "пр",
            "тыс",
            "руб",
            "коп",
            "ул",
            "обл",
        }
    ),
    "pt": frozenset(
        {"sr", "sra", "dr", "dra", "prof", "profa", "ex", "av", "núm", "pág", "etc", "ltda", "esq"}
    ),
}

_PARA_SPLIT_RE = re.compile(r"\n[ \t]*\n+")
_SENT_PUNCT_RE = re.compile(r"[.!?…]+")
_LAST_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)
# Characters that may begin a new sentence (used after a boundary dot/punct):
# U+201C left double quote, U+2018 left single quote, U+00AB guillemet,
# straight double quote, straight single quote, open paren, hyphen, U+2014 em dash.
_SENTENCE_START_CHARS = "\u201c\u2018\u00ab\"'(-\u2014"


def _trim_to_span(chunk: str, start: int) -> Span:
    """Strip surrounding whitespace from chunk and return a Span with offsets."""
    stripped = chunk.strip()
    lead = len(chunk) - len(chunk.lstrip())
    real_start = start + lead
    return Span(text=stripped, start=real_start, end=real_start + len(stripped))


class RegexSegmenter:
    """Rule-based segmenter for en/ru/pt. Swap-in for the Segmenter protocol."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self._abbrevs = _ABBREVIATIONS.get(lang, frozenset())

    def split_paragraphs(self, text: str) -> list[Span]:
        spans: list[Span] = []
        pos = 0
        for m in _PARA_SPLIT_RE.finditer(text):
            chunk = text[pos : m.start()]
            if chunk.strip():
                spans.append(_trim_to_span(chunk, pos))
            pos = m.end()
        tail = text[pos:]
        if tail.strip():
            spans.append(_trim_to_span(tail, pos))
        return spans

    def split_sentences(self, paragraph: str, *, base_offset: int = 0) -> list[Span]:
        spans: list[Span] = []
        n = len(paragraph)
        start = 0
        for m in _SENT_PUNCT_RE.finditer(paragraph):
            end = m.end()
            after = paragraph[end : end + 1]
            # Boundary candidate only when followed by whitespace or end-of-text.
            if after and not after.isspace():
                continue
            # Skip abbreviations and single-letter initials right before the dot.
            prefix = paragraph[start : m.start()]
            lw = _LAST_WORD_RE.search(prefix)
            if lw is not None:
                word = lw.group(1)
                is_abbrev = word.lower() in self._abbrevs or len(word) == 1
                if is_abbrev:
                    # For compound abbreviations like "т.д." the last component
                    # is preceded by a dot (e.g. prefix ends in "т.д").  In that
                    # case we only suppress the split when the following word
                    # does NOT start with an uppercase letter — otherwise we let
                    # the sentence-start check below decide.
                    in_compound = lw.start() > 0 and prefix[lw.start() - 1] == "."
                    if not in_compound:
                        continue
                    # Compound abbreviation: look ahead to see if what follows
                    # is a real sentence start (uppercase).  If not, suppress.
                    j_peek = end
                    while j_peek < n and paragraph[j_peek].isspace():
                        j_peek += 1
                    if j_peek >= n or not paragraph[j_peek].isupper():
                        continue
                    # Falls through to the normal sentence-start check below.
            # Require the next non-space char to look like a sentence start.
            j = end
            while j < n and paragraph[j].isspace():
                j += 1
            if j < n:
                nxt = paragraph[j]
                if not (nxt.isupper() or nxt.isdigit() or nxt in _SENTENCE_START_CHARS):
                    continue
            spans.append(_trim_to_span(paragraph[start:end], base_offset + start))
            start = end
        tail = paragraph[start:]
        if tail.strip():
            spans.append(_trim_to_span(tail, base_offset + start))
        return spans
