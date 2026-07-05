# Reader Page — Design

- **Date:** 2026-07-05
- **Status:** ✅ Implemented on `feature/FLQ-4-reader-page` (Tasks 1–11 + final-review fixes; backend 175 + frontend 48 tests pass, all gates clean). Reconciled with the shipped code 2026-07-05.
- **Backlog task:** FLQ-4 (`backlog/tasks/flq-4 - Reader-page-sentence-page-modes-token-highlighting-navigation.md`)
- **Branch (planned):** `feature/FLQ-4-reader-page`
- **Canonical inputs:** `docs/ui/reader.md` (UI spec, binding for layout/states/hotkeys), `docs/adr/ADR-0005-word-status-model-lingq-levels.md`, `docs/architecture/2026-04-11-mvp-domain-model.md` (§7, §8.2), ADR-0001, ADR-0003
- **Implementation plan:** `.superpowers/plans/2026-07-05-reader-page.md`

## Why

The Reader is the core product experience: read a lesson with status-highlighted tokens, click a word for its card, promote the remaining `new` words to `known` on page turn. FLQ-1 produced segments and token occurrences; FLQ-2/3 produced the translation sources the Word Card will use. This change renders it all: the reader page itself, plus the missing persistence layer it stands on (`token_items`, `reader_positions`, `bulk_actions`, `lesson_segment_translations`).

## Goals

- Route `/learn/$lang/lessons/$lessonId` with `page` and `sentence` view modes (reader.md §3–5).
- LingQ-shaped content API: the WHOLE tokenized lesson in one user-independent response; client-side pagination; statuses as a separate lightweight map (user-approved after analyzing LingQ's v3 lesson payload).
- Token highlighting per ADR-0005 (`new` pale blue, `tracked` yellow, `known`/`ignored` plain).
- Per-page bulk-known with undo (toast + `Ctrl+Z`), server-derived from an ordinal range.
- Reader position persistence (debounced) and resume.
- On-demand sentence translation («Показать перевод» in sentence mode): lazily translated via the FLQ-3 gateway on first request, persisted per `(segment, target_lang)` — instance-wide, so repeat views cost nothing.
- Full `token_items` schema per domain model §8.2 (FLQ-6 inherits the table as-is).
- Hotkeys `←/→`, `m`, `Esc`, `Ctrl+Z` (lesson-scoped: undo disarms on lesson change); mobile swipe + bottom-sheet per reader.md §13. *(Shipped note: `f` remains unwired and `s` toggles a stub sidebar state with no panel — both land with FLQ-5's real sidebar/card; tracked in the follow-up task.)*

## Non-Goals

- Phrase selection & phrase highlighting (reader.md §11) — deferred to FLQ-5 with the Word Card (user decision 2026-07-05).
- Word Card itself — FLQ-4 ships a placeholder panel (`WordCardPlaceholder`) that FLQ-5 replaces; clicking a token opens it (AC#3).
- Review-from-page — button rendered disabled ("скоро", FLQ-7).
- TTS/audio, AI text simplification, hidden-translation mode for `page` mode, bilingual view, streak — reader.md §16.
- Prefetching translations for the whole lesson at import (couples the pipeline to AI; on-demand + persistence covers the UX).
- Confidence gradient in `tracked` highlight (uniform yellow, ADR-0005 open question).
- Vocab mini-cards' translations under the sentence — the block renders from `tracked` items, which can't exist before FLQ-5/6 creates them; machinery wired, list empty until then.

## Constraints (from canonical docs)

- **ADR-0005**: `new` is computed (no row = new); bulk-known on "Next page" touches ONLY `new` occurrences; undo required; `ignored` never counted as known.
- **§8.2**: `token_items` unique `(user_id, language_code, token_text)`; `token_text` stored normalized (the FLQ-1/2 join key — `flinq.core.textnorm.normalize_token` output, never recompute differently); check constraints on `confidence 0..5` ↔ `status='tracked'`.
- **§2.4/§6.5**: occurrences have NO FK to `token_items`; the link is computed via `(user_id, lesson.language_code, normalized_text)`.
- **§7.1**: one reader position per `(user_id, lesson_id)`; `view_mode`, `current_segment_id`, `current_token_ordinal`.
- **ADR-0003**: sentence translation is an AI call → kill-switch honored, metadata-only audit, response labeled AI-generated in UI.
- **reader.md**: view mode is client state, NOT a URL param; deviations from the LingQ mockups listed in §4 are already decided.
- Access rule: lesson readable iff owned by the user or `visibility='shared'` (same rule as existing lesson endpoints).

Stack: backend — existing (FastAPI, SQLAlchemy 2 async, Alembic); frontend — React 19 + TS strict, TanStack Router/Query, Zustand, Tailwind v4, Vitest.

## API contracts (module `reader_state`, router prefix `/api`)

All endpoints session-auth (same `_require_user`); lesson access checked (404 unknown, 403 foreign private).

### 1. `GET /api/lessons/{id}/content` — user-independent tokenized lesson

Built from `lesson_segments` + `lesson_token_occurrences`; heterogeneous token stream (LingQ-style), whitespace derived from offset gaps against `raw_text`.

```json
{
  "lesson_id": "…", "language_code": "pt", "word_count": 812,
  "paragraphs": [
    { "sentences": [
        { "seg_id": "…", "index": 3, "text": "O edifício antigo…", "normalized_text": "o edifício antigo…",
          "tokens": [ {"t": "O", "n": "o", "i": 14}, {"ws": " "}, {"t": "edifício", "n": "edifício", "i": 15}, {"p": "."} ] } ] }
  ]
}
```

- `t/n/i` = surface / normalized / `ordinal_in_lesson` (word-like tokens only); `ws` = whitespace run; `p` = punctuation. Short keys deliberate — this payload is the big one; served with gzip (`GZipMiddleware` is NOT currently in `main.py` — this change adds it app-wide, minimum_size ~1KB).
- `word_count` = count of word-like occurrences. Progress % is client-computed from the bookmark ordinal.
- Paragraph grouping (reconciled with reality): the FLQ-1 pipeline persists ONLY `sentence` segment rows — this spec's original assumption of stored paragraph rows was wrong. Paragraph spans are recomputed at request time via the same pure `RegexSegmenter.split_paragraphs(raw_text)` used at import (language-independent, deterministic on the immutable `raw_text` of a `ready` lesson). **This makes `split_paragraphs` load-bearing for already-imported lessons — treat it as frozen, like `normalize_token`.** Long-term fix (follow-up): persist paragraph segments in the FLQ-1 pipeline.

### 2. `GET /api/lessons/{id}/token-statuses` — the user's status map for this lesson's words

```json
{ "statuses": { "edifício": {"s": "tracked", "c": 2}, "o": {"s": "known"} } }
```

Only words having a `token_items` row (absent = `new`). Query: distinct `normalized_text` of the lesson's word-like occurrences ∩ `token_items` for `(user, lesson.language_code)`. Light; re-fetched after bulk/undo/card mutations.

### 3. `PUT /api/reader/positions` — upsert, debounced (~2s) on scroll/navigation

Request `{lesson_id, view_mode: "page"|"sentence", current_segment_id, current_token_ordinal}` → 204. `GET /api/lessons/{id}` (existing endpoint) is extended with `"reader_position": {...} | null` for resume (AC#1).

### 4. `POST /api/reader/bulk-known` — page turn promotion

Request `{lesson_id, from_ordinal, to_ordinal}`. The SERVER derives the affected set (client can't smuggle arbitrary words): word-like occurrences of the lesson in `[from, to]` whose `normalized_text` has no `token_items` row → `INSERT token_items(status='known') ON CONFLICT DO NOTHING`; one `bulk_actions` row (`action_type='bulk_known'`, `payload_json={"token_item_ids": [...]}`, `page_fingerprint=f"{from}:{to}"`). Response `{action_id, created_count}`.

### 5. `POST /api/reader/bulk-actions/{id}/undo`

Deletes payload items that are STILL `status='known'` (user may have edited one meanwhile — those survive), sets `undone_at`. Second undo → 409. Response `{undone_count}`.

### 6. `POST /api/lessons/{id}/segments/{segId}/translation` — «Показать перевод»

Request `{target_language_code: "en"|"ru"|"pt"}`.
1. Stored row in `lesson_segment_translations` → return it (no AI call, no audit).
2. Else `llm_enabled=false` → 503 `ai_disabled`.
3. Else translate via a new `ai_translation.translate_sentence(...)` (same provider/kill-switch/audit machinery as hints, different prompt: full-sentence translation, single string), store, return.

```json
{ "text": "Старое здание стоит на площади.", "source": "ai", "model": "gpt-4o-mini", "stored": false }
```

Translations are instance-wide (keyed by segment, not user) — deliberate: lesson content is already shared, its translation is content too. UI labels it AI-generated (ADR-0003).

## Data model (migration 0006, module `flinq/modules/reader_state/` + `token_items` housed in `flinq/modules/vocabulary/models.py` so FLQ-6 finds it home)

```
token_items                      — §8.2 verbatim
  id UUID PK, user_id FK users ON DELETE CASCADE, language_code text,
  token_text text (normalized), status text ('tracked'|'known'|'ignored'),
  confidence int NULL, created_from_occurrence_id UUID NULL (no FK — §2.4 spirit),
  created_at, updated_at
  UNIQUE (user_id, language_code, token_text)
  CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 5)
  CHECK ((status = 'tracked') = (confidence IS NOT NULL))   — tracked always has confidence, others never (§8.2 + ADR-0005)
  INDEX (user_id, language_code)

reader_positions                 — §7.1
  id UUID PK, user_id FK CASCADE, lesson_id FK lessons CASCADE,
  view_mode text, current_segment_id UUID NULL, current_token_ordinal int NULL,
  last_opened_at timestamptz
  UNIQUE (user_id, lesson_id)

bulk_actions                     — §7.2
  id UUID PK, user_id FK CASCADE, lesson_id FK CASCADE,
  action_type text ('bulk_known'), page_fingerprint text,
  payload_json jsonb, created_at, undone_at timestamptz NULL

lesson_segment_translations
  id UUID PK, segment_id FK lesson_segments ON DELETE CASCADE,
  target_language_code text, translation_text text, source text ('ai'), model text,
  created_at
  UNIQUE (segment_id, target_language_code)
```

## Frontend architecture

```
routes/learn.$lang.lessons.$lessonId.tsx    — route, processing/failed/skeleton states (§12; poll 2s while processing)
features/reader/
  ReaderPage.tsx        — orchestration, hotkeys, position debounce
  PageView.tsx          — client pagination (group sentences until ≥250 word tokens, sentence-aligned), Prev/Next
  SentenceView.tsx      — one sentence centered, «Показать перевод ▾» (lazy query), vocab mini-list (tracked ∩ sentence)
  TokenSpan.tsx         — memoized span; bg via --reader-new-bg / --reader-tracked-bg (CSS vars, ADR-0005)
  ReaderTopBar.tsx      — progress %, [Aa] font popover (size/line-height/serif → localStorage), [X] close → library
  BottomToolbar.tsx     — mode toggle, Review-from-page (disabled stub)
  WordCardPlaceholder.tsx — right floating panel (desktop) / bottom sheet (mobile); shows token + status; FLQ-5 replaces
  UndoToast.tsx         — "N слов помечены как known" + Отменить (6s, and Ctrl+Z while action undoable)
  readerStore.ts        — Zustand: mode, currentOrdinal, font prefs, sidebar, lastBulkActionId
  useReaderQueries.ts   — content (staleTime: Infinity), statuses (invalidated on mutations), position mutation,
                          bulkKnown/undo mutations, sentence translation query (enabled on demand)
  pagination.ts         — pure page-splitting fn (unit-tested)
```

Flow: «Next page» → `bulkKnown(from,to)` → advance page → invalidate statuses → toast with undo. `Esc` closes card, else reader. Swipe left/right on `<md`.

## Testing

- **Backend (pytest + testcontainers):** content reconstruction fidelity (tokens+ws+punct concat == raw_text slice for a fixture lesson); statuses join correctness; bulk-known — only `new` in range, ON CONFLICT safe on repeat, tracked/ignored untouched (ADR-0005); undo — partial survival when an item changed status, 409 on double undo; positions upsert; sentence translation — stored-hit makes zero provider calls, miss+disabled → 503, miss+fake provider → stores and returns; access — 404/403 on foreign private lesson for every endpoint.
- **Frontend (Vitest + @testing-library/react):** `pagination.ts` boundaries (exact 250 crossing, single giant sentence); `TokenSpan` class per status incl. absent-status=new; bulk→toast→undo flow with mocked API; hotkeys dispatch; «Показать перевод» lazy fetch + AI-label; processing state polling.

## Deferred follow-ups

- Phrase selection + phrase highlight → FLQ-5.
- Vocab mini-cards populated with translations → after FLQ-5/6.
- `reader_view_mode` default in `user_settings` (per-lesson `reader_positions.view_mode` covers resume; a global default is polish).
- Configurable page size in settings (constant 250 for MVP).
- Review-from-page wiring → FLQ-7.
