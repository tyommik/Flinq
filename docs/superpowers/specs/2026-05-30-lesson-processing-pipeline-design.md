# Lesson Processing Pipeline — Design

- **Date:** 2026-05-30
- **Backlog task:** FLQ-1 (`backlog/tasks/flq-1 - Lesson-processing-pipeline-segmentation-tokenization-occurrences.md`)
- **Branch:** `feat/flq-1-lesson-pipeline`
- **Canonical inputs:** `docs/architecture/2026-04-11-mvp-domain-model.md` (§2, §6, §14, §15), `docs/adr/ADR-0001-unit-of-learning-token-level.md`

## Why

The current `lessons` slice stores `raw_text` as a single blob and marks every lesson `ready` on creation — there is no segmentation, no token occurrences, and no import job lifecycle. Every token-level MVP feature (reader highlighting, word status, vocabulary lookup, coverage) is built on token occurrences, so without this pipeline the Reader cannot function. This change extends the lesson library to the full text-processing model from domain model §6.

## Goals

- Persist the full lesson-facts model: sources, segments, token occurrences, import jobs.
- Asynchronous import: `POST` returns 202 immediately; a worker job does the processing; clients poll status.
- Deterministic, reproducible segmentation + tokenization for EN/RU/PT.
- Retry that is idempotent and cannot corrupt a `ready` lesson.
- A single shared normalization function reused by the future vocabulary layer.

## Non-Goals

- Re-importing a `ready` lesson (no content versioning beyond v1 in MVP).
- Reader, vocabulary, SRS behavior; `reader_positions` / `lesson_progress`.
- File-upload endpoint (`.txt`/`.md` upload is FLQ-10); this change processes text already on the lesson.
- Phrase occurrences, lemma, trigram search indexes (later).

## Constraints (from canonical docs)

- **§14.1 — content immutable after `ready`**: once a lesson is `ready`, its occurrences and segment order must not be silently rewritten.
- **§2.4 / §6.5 — no FK from occurrence to knowledge**: `lesson_token_occurrences` must NOT reference `token_items`. The link is computed later by `(user_id, lesson.language_code, normalized_text)`. The pipeline therefore owns the canonical `normalized_text`.
- **§15 — uniqueness**: `lesson_segments(lesson_id, ordinal)` and `lesson_token_occurrences(lesson_id, ordinal_in_lesson)`.
- **ADR-0001 — token unit**: NFC, lowercase, trim leading/trailing punctuation, preserve diacritics and internal hyphens/apostrophes; surface form is the learning unit (no lemma).

Stack: Python 3.13, async SQLAlchemy 2 (`Mapped[...]`), Pydantic v2, taskiq worker (existing broker), Postgres, loguru. Target learning languages: `en`, `ru`, `pt`.

## Decisions

### 1. No re-import of a `ready` lesson in MVP → `ready` is terminal

Lesson lifecycle is near-acyclic: `processing → ready` (terminal) or `processing → failed → (retry) → processing`. Re-importing finished content is out of scope.

- **Why**: It removes the only real conflict in the task — idempotent retry (AC#6) vs immutability (§14.1). Because we never mutate a `ready` lesson, "delete-and-recreate on retry" is safe *by construction*.
- **Guard**: destructive delete+recreate of segments/occurrences is allowed **iff** `lesson.status ∈ {processing, failed}`; for `ready` it is refused. §14.1 holds with no extra mechanism.
- **Alternative considered**: full source versioning with active-version pointer swaps — deferred (see Decision 2); more moving parts than MVP needs.

```
   ┌────────────┐  job ok    ┌─────────┐
   │ processing │───────────▶│  ready  │ ◀── terminal, immutable
   └─────┬──────┘            └─────────┘
         │ job fail
         ▼
   ┌──────────┐   retry (only while NOT ready)
   │  failed  │──────────┐
   └──────────┘          ▼
         ▲────────── processing
```

### 2. Versioning = "keep the seam" (Variant A)

Create `lesson_sources` with `version_number` and `lessons.current_source_version`, but in MVP there is always exactly one source row with `version_number = 1` and `current_source_version = 1`.

- **Why**: The schema matches domain model §6 and stays ready for a future re-import feature with no migration on a live DB. The cost is one always-`1` column and one always-single-row table — effectively free.
- **Alternative**: a thin 1:1 `lesson_source` without version columns — rejected: a future re-import would then require a schema migration in production.

### 3. Asynchronous processing (202 + worker job + polling)

`POST /api/lessons` creates `lessons(status=processing)` + `lesson_sources(v1)` + a `lesson_import_jobs(pending)` row, enqueues a taskiq task, and returns **202** `{id, status}`. `GET /api/lessons/{id}` polls until `ready`/`failed`.

- **Why**: Segmentation/tokenization on a large text should not block the web worker; the job table gives an auditable lifecycle (`pending → running → done|failed`, `error_message`).
- **Trade-off**: more surface than synchronous processing (job table, polling, eventual consistency). Accepted because it is the honest shape for variable-size imports and matches the task's intent (labels: backend, worker).
- **Note**: the import service function is callable directly (without a live worker) so tests and a future synchronous path can reuse it.

### 4. Segmentation: built-in `RegexSegmenter` behind a `Segmenter` protocol

Implement our own segmenter; do not take an external dependency.

- **Why no library**: `pysbd` has no Portuguese; `yasbd-lib` covers neither Russian nor Portuguese and is a 1-day-old alpha (v0.1.0, single author). Both fail to cover EN+RU+PT, which is the whole requirement (AC#2).
- **Design**: a narrow `Segmenter` `Protocol` (`split_paragraphs`, `split_sentences`) with a `RegexSegmenter` implementation. A mature library can later be dropped in as another `Segmenter` without touching the pipeline.
- **Quality bar (MVP)**: paragraphs split on blank lines (`\n\s*\n`); sentences split on `[.!?…]+` with guards for per-language abbreviations (`Mr.`, `и т.д.`, `Dr.ª`, …), initials (`А. С.`), decimals (`3.14`), and ellipsis. Target ~90%+ on a small golden set per language; higher accuracy is iteration, not an MVP blocker.
- **Shared normalization**: `normalize_token()` lives in the same module and produces `normalized_text` for occurrences. It is the canonical join key with future `token_items` (§2.4) — the pipeline and the vocabulary layer MUST use this one function so highlighting cannot silently break.

### 5. Tokenization rules (ADR-0001)

Per occurrence: keep `surface_text` (original form from the text) and `normalized_text = normalize_token(surface)`:

- Unicode NFC; lowercase; strip leading/trailing punctuation.
- Preserve diacritics and word-internal hyphens/apostrophes (`co-op`, `l'eau`, `что-то`).
- `is_word_like = false` for punctuation-only occurrences (still recorded to preserve `ordinal_in_lesson` continuity).

## Architecture & Data Flow

```
POST /api/lessons (text, lang, title?, visibility?)
   │  create lessons(status=processing, current_source_version=1)
   │  create lesson_sources(version_number=1, content_hash, source_type=manual)
   │  create lesson_import_jobs(status=pending)
   │  enqueue taskiq → return 202 {id, status:processing}
   ▼
worker job (lesson_import_jobs):
   guard: lesson.status ∈ {processing, failed}          ← idempotency gate
   job.status=running, started_at
   delete existing segments+occurrences (no-op on first run)
   NFC → split_paragraphs → split_sentences → tokenize(normalize_token, is_word_like)
   bulk insert lesson_segments, lesson_token_occurrences
   set lessons.word_count, segment_count, status=ready
   job.status=done, finished_at
   on exception: lessons.status=failed, job.status=failed, job.error_message
   ▼
GET /api/lessons/{id} → {status, word_count, segment_count, ...}  (poll until ready/failed)
```

### Data model (domain model §6)

New tables:

- **`lesson_sources`** — `id, lesson_id (FK→lessons, CASCADE), source_type ('manual'|'file'|'url'|'ocr'), source_uri, original_filename, content_hash, author, license, source_label, version_number, created_at`.
- **`lesson_segments`** — `id, lesson_id (FK, CASCADE), ordinal, segment_type ('sentence'|'paragraph'), text, start_char_offset, end_char_offset`. **Unique `(lesson_id, ordinal)`**.
- **`lesson_token_occurrences`** — `id, lesson_id (FK, CASCADE), segment_id (FK→lesson_segments), ordinal_in_lesson, ordinal_in_segment, surface_text, normalized_text, start_char_offset, end_char_offset, is_word_like`. **Unique `(lesson_id, ordinal_in_lesson)`**. No FK to `token_items`.
- **`lesson_import_jobs`** — `id, lesson_id (FK, CASCADE), requested_by_user_id, job_type, status ('pending'|'running'|'done'|'failed'), payload_json, error_message, started_at, finished_at`. Index `(lesson_id, status)`.

New columns on **`lessons`**: `segment_count`, `current_source_version`.

### Module boundaries

- `modules/lesson_library/tokenization.py` — `Segmenter` Protocol, `RegexSegmenter`, `normalize_token()`, tokenizer. **Pure functions, no DB** — fully unit-testable.
- `modules/lesson_library/service.py` (+ `repo.py`) — import orchestration: takes `lesson_id` + text + session, runs segment→tokenize→bulk-insert, sets counts/status. Idempotent. Callable without a worker.
- `worker/tasks.py` — taskiq task wrapping the service, managing the `lesson_import_jobs` row and final lesson status.
- `api/lessons.py` — `POST` (202 + enqueue), `GET /{id}` (poll), existing list `GET` preserved.

## Requirements ↔ Acceptance Criteria

| AC | Requirement |
|----|-------------|
| #1 | Migration adds `lesson_sources`, `lesson_segments`, `lesson_token_occurrences`, `lesson_import_jobs` + `lessons` columns. |
| #2 | Worker segments by paragraph/sentence and tokenizes with NFC + lowercase + trim outer punctuation (preserve diacritics + internal hyphens/apostrophes) + `is_word_like`, for EN/RU/PT. |
| #3 | `POST /api/lessons` returns 202 and enqueues a job; lesson starts in `processing`. |
| #4 | Lesson → `ready` after the worker job, or `failed` with `error_message` on error. |
| #5 | Uniqueness `(lesson_id, ordinal_in_lesson)` on occurrences (and `(lesson_id, ordinal)` on segments). |
| #6 | Tests: import round-trip, EN/RU/PT segmentation correctness, retry idempotency. |

## Error Handling

- Any exception during processing → lesson `failed`, `lesson_import_jobs.error_message` set, `finished_at` stamped.
- Retry is safe to re-enqueue: the service deletes existing segments/occurrences before re-inserting, guarded by `status ∈ {processing, failed}`. A `ready` lesson is never mutated.
- Unauthenticated requests to lesson endpoints → 401. All endpoints require the current user.

## Testing Strategy

- **Unit (no DB)** — `tokenization.py`: `normalize_token()` (diacritics, internal `-`/`'`, NFC, lowercase, outer-punct trim), `is_word_like`, `RegexSegmenter` on EN/RU/PT golden samples (abbreviation non-splits, initials, decimals, ellipsis, paragraph/sentence counts). (AC#2)
- **API** — `POST /api/lessons` → 202 + `processing`, `lesson_import_jobs` row created. (AC#3)
- **Round-trip** — run the import service directly → lesson `ready`, occurrences exist, `(lesson_id, ordinal_in_lesson)` unique, segments ordered. (AC#1, #5)
- **Idempotency** — run the import service twice for the same non-`ready` lesson → occurrence/segment counts do not double. (AC#6)
- **Failure** — error path sets lesson `failed` + job `error_message`. (AC#4)
- Integration tests call the import service directly rather than relying on a running taskiq worker. Note any Docker/Postgres testcontainer limitations in CI.

## Migration Plan

- One new Alembic revision (down_revision = current head `0002_lessons_minimal`) creating the four tables with §15 unique constraints and FKs (`ON DELETE CASCADE` from `lessons`), plus `ALTER lessons` to add `segment_count` and `current_source_version`.
- Register the new models module in `backend/migrations/env.py` so autogenerate/metadata sees them.
- No data backfill: existing lessons (if any) predate the pipeline; no production data to migrate in the MVP skeleton.

## Open Questions

- Persist punctuation-only occurrences (chosen: yes, for ordinal continuity) vs skip and make ordinals sparse? Revisit if reader rendering prefers word-only ordinals.
- Job retry trigger: manual re-enqueue vs automatic taskiq retry policy — MVP assumes manual/explicit re-enqueue; revisit when failure modes are observed.
