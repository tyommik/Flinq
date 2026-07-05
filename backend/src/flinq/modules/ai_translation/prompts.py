"""Hardcoded contextual-translation prompt + hint parsing (spec Decisions 1-2).

Pure functions, no I/O. The prompt is deterministic: inputs are normalized
(NFC + whitespace collapse) so the audit prompt_hash is stable against
trivial client-side differences in how the sentence was cut.
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_LEAD_JUNK_RE = re.compile(r"^\s*(?:[-*•·]+\s+|\d+[.)]\s*)")
_QUOTES = "\"'«»„“”‚‘’"  # noqa: RUF001 -- U+2019 etc. are the point

LANGUAGE_NAMES: dict[str, str] = {"en": "English", "ru": "Russian", "pt": "Portuguese"}

SYSTEM_PROMPT = (
    "You are a translation assistant inside a language-learning reader. "
    "Reply with 1 to 3 short translation variants only, one per line, best first. "
    "No numbering, no explanations, no quotes."
)


def normalize_ai_text(text: str) -> str:
    """NFC + collapse whitespace runs + strip. Keeps the prompt (and its hash) stable."""
    return _WS_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def build_hints_prompt(
    *, surface_text: str, context_text: str, target_language_code: str
) -> tuple[str, str]:
    """Return (system, user) messages for the hints request."""
    surface = normalize_ai_text(surface_text)
    context = normalize_ai_text(context_text)
    user = (
        f"Sentence: {context}\n"
        f"Word or phrase: {surface}\n"
        f"Translate the word or phrase as it is used in this sentence "
        f"into {LANGUAGE_NAMES[target_language_code]}."
    )
    return SYSTEM_PROMPT, user


def parse_hints(text: str) -> list[str]:
    """Model output -> up to 3 clean, deduplicated hint strings (order preserved)."""
    hints: list[str] = []
    for line in text.splitlines():
        cleaned = _LEAD_JUNK_RE.sub("", line).strip().strip(_QUOTES).strip()
        if cleaned and cleaned not in hints:
            hints.append(cleaned)
        if len(hints) == 3:
            break
    return hints
