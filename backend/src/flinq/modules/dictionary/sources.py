"""Where each covered language pair's Kaikki dump lives (spec: coverage table)."""

from __future__ import annotations

from dataclasses import dataclass

_EN_EDITION = "https://kaikki.org/dictionary"

# Russian edition (ruwiktionary), Portuguese language section. The Russian
# name for Portuguese, "Португальский", percent-encoded (verified live on
# kaikki.org — see the DUMP_SOURCES comment below for the verification note).
_RU_PT_NAME = "%D0%9F%D0%BE%D1%80%D1%82%D1%83%D0%B3%D0%B0%D0%BB%D1%8C%D1%81%D0%BA%D0%B8%D0%B9"
_RU_EDITION_PT_DIR = f"https://kaikki.org/ruwiktionary/{_RU_PT_NAME}"
_RU_EDITION_PT_FILE = f"kaikki.org-dictionary-{_RU_PT_NAME}.jsonl"


@dataclass(frozen=True)
class DumpSource:
    url: str


# URLs verified against kaikki.org on 2026-07-04 (Task 4 Step 1). The pt->ru
# URL comes from the Russian edition (ruwiktionary) section of kaikki.org,
# under the Russian-language name for Portuguese ("Португальский",
# percent-encoded above); that edition only publishes a plain .jsonl (no
# .gz variant), per the brief's documented gz-then-plain fallback.
DUMP_SOURCES: dict[tuple[str, str], DumpSource] = {
    ("en", "ru"): DumpSource(f"{_EN_EDITION}/English/kaikki.org-dictionary-English.jsonl.gz"),
    ("en", "pt"): DumpSource(f"{_EN_EDITION}/English/kaikki.org-dictionary-English.jsonl.gz"),
    ("ru", "en"): DumpSource(f"{_EN_EDITION}/Russian/kaikki.org-dictionary-Russian.jsonl.gz"),
    ("pt", "en"): DumpSource(f"{_EN_EDITION}/Portuguese/kaikki.org-dictionary-Portuguese.jsonl"),
    ("pt", "ru"): DumpSource(f"{_RU_EDITION_PT_DIR}/{_RU_EDITION_PT_FILE}"),
}
