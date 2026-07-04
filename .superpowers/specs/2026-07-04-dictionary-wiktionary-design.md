# Dictionary: Wiktionary Provider — Design

- **Date:** 2026-07-04
- **Status:** ✅ Implemented on `feat/flq-2-dictionary-wiktionary` (Tasks 1–8 + final-review fixes; 114 tests pass, ruff/pyright clean). Reconciled with the shipped code 2026-07-04.
- **Backlog task:** FLQ-2 (`backlog/tasks/flq-2 - Wiktionary-dictionary-provider-import-lookup-endpoints.md`)
- **Branch (planned):** `feat/flq-2-dictionary-wiktionary`
- **Canonical inputs:** `docs/architecture/2026-04-11-mvp-domain-model.md` (§9, §15), `docs/adr/ADR-0004-dictionary-wiktionary-provider.md`, `docs/adr/ADR-0001-unit-of-learning-token-level.md`
- **Implementation plan:** `.superpowers/plans/2026-07-04-dictionary-wiktionary.md`

## Why

The Word Card (FLQ-5) must show translation suggestions when the user clicks a token in the reader. Today there is no translation source at all. This change builds the built-in dictionary layer: Wiktionary data imported into the instance's own Postgres, looked up instantly and offline — the "cheap first answer" that keeps a self-hosted install useful without AI keys (spec §16.6: dictionary primary, AI supplementary). It also ships the external-dictionary link-out buttons (Lingvo, WordReference, Google Translate, …) so the card always offers *something*, even for pairs the local data does not cover. Contextual AI translation is FLQ-3 and sits on top.

## Goals

- Persist dictionary data: `dictionary_source_versions`, `dictionary_entries`, `dictionary_translations`, `dictionary_examples` (domain model §9).
- One admin command per language pair: `flinq dictionary refresh --lang <src> --target <dst> [--file PATH]` — download (or read local file), stream-parse, bulk-load, atomically activate. Refresh never leaves the dictionary empty or serves a half-imported version.
- `GET /api/dictionary/lookup` returning entries + translations + examples, CC-BY-SA attribution, and rendered external-dictionary links.
- `DictionaryProvider` abstraction ready for Phase-2 providers (ADR-0004).
- One shared normalization function for the token↔dictionary join key — closing the FLQ-1 follow-up (`casefold`, U+2019 apostrophe).

## Non-Goals

- RU→PT and any pair not listed in the coverage table (LLM + link-outs cover the gaps).
- Inflected-form lookup (`buildings` → `building`) via Kaikki `forms` — deferred; exact-match on the normalized headword only.
- Provider chaining / priorities, admin provider config UI (FLQ-11), periodic auto-refresh (ADR-0004: manual admin action).
- Word Card UI (FLQ-5) — this change only serves the API it will call.
- Storing raw JSONL dumps (ADR-0004: only version metadata is kept).

## Constraints (from canonical docs)

- **ADR-0004 — offline-first**: lookup must work with zero external calls; data lives in the instance's Postgres.
- **ADR-0004 — attribution is not optional**: CC-BY-SA attribution must be part of the lookup response so the UI cannot forget it.
- **ADR-0001 / FLQ-1 — join key**: reader tokens are matched to dictionary headwords by normalized text. Both sides must use the *same* function. FLQ-1's `normalize_token` currently uses `.lower()` and misses U+2019; the deferred fix lands here, before any layer builds on the key.
- **§15 — uniqueness**: one active source version per language pair; entries keyed by `(source_version_id, entry_key)`.

Stack: Python 3.13, async SQLAlchemy 2, Pydantic v2, Postgres (asyncpg), httpx, loguru, testcontainers. Languages: `en`, `ru`, `pt`.

## Language-pair coverage

Kaikki.org publishes machine-readable extracts of Wiktionary *editions*. The English edition covers pairs involving English in both directions; the Russian edition covers PT→RU. Exact download URLs are resolved from a config mapping (verified against kaikki.org during implementation).

| Pair   | Dump (edition / language)         | Translation source in the record          |
|--------|-----------------------------------|-------------------------------------------|
| EN→RU  | English edition / English         | `translations[]` filtered to `code == ru` |
| EN→PT  | English edition / English         | `translations[]` filtered to `code == pt` |
| RU→EN  | English edition / Russian         | sense glosses (English text)              |
| PT→EN  | English edition / Portuguese      | sense glosses (English text)              |
| PT→RU  | Russian edition / Portuguese      | sense glosses (Russian text)              |

Uncovered pairs return an empty `entries` list (HTTP 200) — the response still carries `external_links`, and FLQ-3's LLM covers contextual translation.

## Decisions

### 1. Version scoped to a language pair; atomic activation

`dictionary_source_versions` rows are keyed by `(source_language_code, target_language_code)`. Each `refresh` run creates a new version in status `importing`, loads everything under it, then in one transaction flips it to `active` and deletes prior versions of the same pair (cascading to their entries).

- **Why**: readers keep hitting the old active version for the whole import; there is no empty-dictionary window and no partially visible data. A failed import leaves a `failed` version row (for diagnostics) and the old active untouched.
- **Cost accepted**: English-edition entries are duplicated between the `en→ru` and `en→pt` versions. Storage is cheap; the model and the failure story stay simple.
- **Alternative**: one version per *dump* shared by several pairs — rejected: activation and rollback semantics get entangled across pairs for no user-visible benefit.
- **Guard**: partial unique index — at most one `active` version per `(source_language_code, target_language_code)`.

Version lifecycle: `importing → active` (success) or `importing → failed`; `active → superseded/deleted` only by the next successful import of the same pair.

### 2. Stream + COPY import

The importer streams the dump (httpx streaming download to a cache dir under the app data directory, or `--file`), parses JSONL line-by-line (constant memory), buffers rows, and bulk-loads with PostgreSQL `COPY` via the raw asyncpg connection (`copy_records_to_table`), batched (~10k rows). Progress is logged every N records (AC#2).

- **Why**: full dumps are hundreds of MB with millions of rows; ORM inserts would take hours, `COPY` takes minutes. Everything loads into a *new* version, so no `ON CONFLICT` handling is needed.
- **Note**: entry/translation/example rows get client-generated UUIDs so the three tables can be COPY-loaded without round-trips for generated keys.
- **Failure handling**: any error (network, parse, DB) marks the version `failed` and aborts; a re-run starts a fresh version. Malformed individual JSONL lines are counted and skipped (logged at the end), not fatal.

### 3. Record mapping (per dump kind)

Every record with `word` and matching `lang_code` becomes one `dictionary_entries` row per part of speech: `headword = word`, `headword_normalized = normalize(word)`, `part_of_speech = pos`, `entry_key = "{word}:{pos}:{etymology_number or 0}"` (deterministic — Kaikki records carry no explicit id), `gloss_summary =` first gloss.

- **English-edition English dump (en→ru / en→pt)**: `translations[]` items with the target `code` become `dictionary_translations` (`translation_text = word` of the translation item, `usage_note` from its `sense` text, `sense_index` best-effort by matching the `sense` text to the glosses, else `0`).
- **Foreign-language dumps (ru→en, pt→en, pt→ru)**: each sense's glosses become `dictionary_translations` rows with `sense_index` = the sense position; gloss language is the pair's target by construction.
- **Examples**: `senses[].examples[].text` (+ translation when present) → `dictionary_examples` with the sense's index. Capped at 5 per entry to keep the table sane.
- Entries that yield zero translations for the pair are skipped entirely.

### 4. Shared normalization = the join key (closes the FLQ-1 follow-up)

`normalize_token` moves from `modules/lesson_library/tokenization.py` to a shared location (e.g. `flinq/core/textnorm.py`, re-exported for backward compatibility) and gets the deferred fix: `.casefold()` instead of `.lower()`, and U+2019 (') treated like the ASCII apostrophe (normalized to `'`). `headword_normalized` is computed with this exact function at import time.

- **Why here**: FLQ-1 notes explicitly say the fix must land *before* a layer builds on the join key. The dictionary is that first layer. Doing it later would require re-importing dictionaries and re-normalizing occurrences.
- **Impact on FLQ-1 data**: normalization of already-imported lesson occurrences changes only for strings affected by casefold/U+2019 differences. `ready` lessons are immutable (FLQ-1 Decision 1), so existing rows are *not* rewritten; dev databases can simply recreate lessons. No production data exists yet.
- Lookup then is: `WHERE source_language_code = :lang AND headword_normalized = normalize(:text)` against the active version — case-insensitivity falls out for free (AC on lookup), no `ILIKE`, no functional index.

### 5. Provider interface: one `lookup` method

```python
class DictionaryProvider(Protocol):
    async def lookup(self, text: str, from_lang: str, to_lang: str) -> DictionaryLookupResult: ...
```

`WiktionaryLocalProvider` is the only MVP implementation (reads Postgres). Multi-word headwords exist in Wiktionary, so phrases go through the same method; ADR-0004's separate `lookup_phrase` is dropped as YAGNI (ADR gets a one-line amendment note).

### 6. Lookup endpoint

`GET /api/dictionary/lookup?lang=<src>&target=<dst>&text=<word>` — session auth required (same middleware as the rest of `/api`). `text` limited to 256 chars. Language codes outside `{en, ru, pt}` → 422; a *valid but uncovered* pair (e.g. ru→pt) is not an error — it returns 200 with empty `entries` (links still rendered).

```json
{
  "entries": [
    {"headword": "building", "part_of_speech": "noun",
     "senses": [{"sense_index": 0, "translation": "здание", "usage_note": null,
                  "examples": [{"text": "...", "translation": "..."}]}]}
  ],
  "attribution": {"source": "Wiktionary (via Kaikki.org)", "license": "CC-BY-SA 4.0",
                   "url": "https://kaikki.org/"},
  "external_links": [
    {"name": "Lingvo Live", "url": "https://www.lingvolive.com/en-us/translate/en-ru/building"}
  ]
}
```

- Empty dictionary result is **200 with `entries: []`** — never 404; `external_links` and `attribution` are always present.
- Translations grouped into senses by `sense_index`; entries ordered by `entry_key` (deterministic and stable — shipped implementation; supersedes the earlier "as imported" wording).
- Read path hits only `active` versions via the partial index; target lookup latency: single-digit ms index scan.

### 7. External dictionary links

Config-driven templates (backend settings, constant defaults):

```python
ExternalDictionary(name="Lingvo Live", url_template="https://www.lingvolive.com/en-us/translate/{from}-{to}/{text}", pairs={...})
```

Defaults: Lingvo Live, WordReference, Google Translate, Wiktionary web, Urban Dictionary (en source only). The server URL-encodes `text` and renders only the templates whose `pairs` match the request. Frontend (FLQ-5) just renders buttons with `target="_blank"`.

- **Why server-side**: one source of truth, works for any client, and the list can later move to admin config (FLQ-11) without touching the frontend.

### 8. CLI

`flinq dictionary refresh --lang pt --target ru [--file dump.jsonl]` on the existing CLI entry point. `--file` bypasses download (air-gapped installs, tests, fixtures). Command is safe to re-run and safe to interrupt (Decision 1). Unsupported pair → clear error listing supported pairs.

## Data model (migration 0004)

```
dictionary_source_versions
  id UUID PK, source_name text ('wiktionary-kaikki'),
  source_language_code text, target_language_code text,
  source_version text (dump date/URL tag), status text (importing|active|failed),
  fetched_at timestamptz, metadata_json jsonb (url, record counts, skipped lines)
  UNIQUE (source_language_code, target_language_code) WHERE status = 'active'   -- partial

dictionary_entries
  id UUID PK, source_version_id FK → versions ON DELETE CASCADE,
  source_language_code text, headword text, headword_normalized text,
  part_of_speech text NULL, entry_key text, gloss_summary text NULL
  INDEX (source_language_code, headword_normalized, source_version_id)
  UNIQUE (source_version_id, entry_key)

dictionary_translations
  id UUID PK, entry_id FK → entries ON DELETE CASCADE,
  target_language_code text, translation_text text,
  sense_index int DEFAULT 0, usage_note text NULL
  INDEX (entry_id)

dictionary_examples
  id UUID PK, entry_id FK → entries ON DELETE CASCADE,
  sense_index int DEFAULT 0, example_text text, example_translation text NULL
  INDEX (entry_id)
```

Module layout: `flinq/modules/dictionary/` (models, repo, service, provider, schemas) + `flinq/cli` gains the `dictionary refresh` subcommand + `flinq/core/textnorm.py` (shared normalization).

## Testing

Small JSONL fixtures (10–20 records each) in `backend/tests/fixtures/dictionary/`, one per dump shape (en-edition English, en-edition Russian/Portuguese, ru-edition Portuguese). Import runs through the real service with `--file` semantics into testcontainers Postgres.

- AC#5: lookup EN→RU, RU→EN, PT→RU known words; unknown word → 200 + empty `entries`.
- Case-insensitivity: `Building` finds `building`; U+2019 apostrophe finds ASCII-apostrophe headword.
- Normalization consistency: `normalize(token)` (tokenizer) == key used by dictionary import for identical strings — one property-style test over tricky samples (ß, d'água, Ё).
- Refresh semantics: second import of the same pair replaces the version; lookups mid-import still serve the old version; failed import leaves old version active.
- External links: correct templates rendered per pair, `text` URL-encoded; Urban only for en.
- Attribution present in every response.
- CLI: unsupported pair errors; malformed JSONL lines skipped and counted.

## Deferred follow-ups

- Inflected-form lookup via Kaikki `forms` (big reader-hit-rate win; own task when Word Card usage data justifies it).
- `lesson_import_jobs.status` index + occurrence re-normalization tooling if normalization changes again (carried from FLQ-1).
- Admin-configurable external links and provider registry (FLQ-11 / Phase 2).
