"""Segmentation and tokenization for lesson text (ADR-0001).

Pure functions only — no DB, no I/O. `normalize_token` is the canonical
join key shared between lesson occurrences and the future vocabulary layer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# A word: a run of word chars that may contain internal hyphens/apostrophes,
# OR a single word char, OR a run of punctuation (non-word, non-space).
_TOKEN_RE = re.compile(r"\w[\w''\-]*\w|\w|[^\w\s]+", re.UNICODE)
_OUTER_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_WORD_CHAR_RE = re.compile(r"\w", re.UNICODE)


@dataclass(frozen=True)
class Token:
    surface_text: str
    normalized_text: str
    start_char_offset: int
    end_char_offset: int
    is_word_like: bool


def normalize_token(surface: str) -> str:
    """NFC, lowercase, strip outer punctuation; keep diacritics + internal -/'."""
    s = unicodedata.normalize("NFC", surface).lower()
    s = _OUTER_PUNCT_RE.sub("", s)
    return s


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
