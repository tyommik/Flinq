"""Canonical text normalization (ADR-0001).

One function shared by lesson occurrences, the dictionary and the future
vocabulary layer. If this ever changes, already-imported data must be
re-imported — treat the algorithm as frozen.
"""

from __future__ import annotations

import re
import unicodedata

_OUTER_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$")
_APOSTROPHES = str.maketrans({"’": "'"})  # noqa: RUF001 -- U+2019 is the point


def normalize_token(surface: str) -> str:
    """NFC, U+2019 -> ', casefold, strip outer punctuation; keep diacritics + internal -/'."""
    s = unicodedata.normalize("NFC", surface).translate(_APOSTROPHES).casefold()
    return _OUTER_PUNCT_RE.sub("", s)
