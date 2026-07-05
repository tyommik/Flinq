# AI Translation Gateway — Design

- **Date:** 2026-07-04
- **Status:** ✅ Implemented on `feature/FLQ-3-ai-translation-gateway` (Tasks 1–5 + final-review fixes; 145 tests pass, ruff/pyright clean). Reconciled with the shipped code 2026-07-05.
- **Backlog task:** FLQ-3 (`backlog/tasks/flq-3 - AI-translation-gateway-OpenAI-compatible-adapter-contextual-translation.md`)
- **Branch (planned):** `feature/FLQ-3-ai-translation-gateway`
- **Canonical inputs:** `docs/adr/ADR-0003-llm-provider-openai-compatible.md`, `docs/architecture/2026-04-11-mvp-domain-model.md` (§11)
- **Implementation plan:** `.superpowers/plans/2026-07-04-ai-translation-gateway.md`

## Why

The Word Card shows AI translation as the first suggestion for `new` words (ADR-0005 card layout) — it is the single AI feature of the MVP (decision log §5). The dictionary (FLQ-2) gives context-free senses; the AI's whole advantage is translating the word *as used in this sentence* ("later" in "See you later" vs "two weeks later"). This change ships the gateway: one OpenAI-compatible adapter, one endpoint, LingQ-hint-shaped output that the Word Card (FLQ-5) merges into its suggestion list next to dictionary senses.

## Goals

- `POST /api/ai/translate`: contextual word/phrase translation returning 1–3 short hint variants, best first.
- `flinq.modules.ai_translation` module with a provider abstraction (`LLMProvider` Protocol) and the single MVP implementation `OpenAICompatibleProvider` (ADR-0003).
- Admin kill-switch: `FLINQ_LLM_ENABLED=false` → 503, zero external calls, zero audit writes.
- Metadata-only audit (`ai_requests`, migration 0005) per ADR-0003 privacy rules: hashes, token counts, latency, status — never raw text.
- Full decoupling from content storage: the gateway reads no lesson tables.

## Non-Goals

- **Response caching** — deferred out of MVP (see Deviations).
- Grammar explanations, chat, exercise generation (ADR-0003: contextual translation only).
- Rate limiting (decision log §11 open question, explicitly out of MVP scope).
- Streaming, multi-provider routing/fallback, admin-editable prompt templates (Phase 2).
- Anthropic/Google native adapters (route through OpenRouter, ADR-0003).
- `ai_requests` retention cleanup job (recommendation ≤30 days stands; enforcement is a follow-up).
- Word Card UI (FLQ-5).

## Deviations (recorded per AGENTS.md rule 3)

1. **No AI response cache in MVP.** ADR-0003 specifies a per-user Redis cache keyed `(user_id, model, prompt_hash)`, TTL 7 days. Deferred: on a single-tenant homelab instance a repeated identical click is rare, one gpt-4o-mini call costs fractions of a cent, and the cache adds a code layer, a TTL setting and a test surface that buy nothing today (user decision, 2026-07-04). `prompt_hash` is still computed and stored in the audit, so adding the cache later is purely additive — no schema or contract change. ADR-0003 itself stays Accepted; this is an MVP scope deferral, not a reversal.
2. **Client supplies the context.** The FLQ-3 task text has the server read the sentence from `segment_id`. Instead the client sends `context_text` directly: the gateway is fully decoupled from content storage (usable tomorrow for cross-segment phrases, import previews, any text) at the cost of trusting the client's sentence cut (user decision, 2026-07-04). `segment_id` is dropped from the request as now meaningless server-side; `lesson_id` stays as optional audit metadata (domain model §11.1 has it nullable).

## Constraints (from canonical docs)

- **ADR-0003 — one adapter**: OpenAI Chat Completions API only; configured by `FLINQ_LLM_BASE_URL` / `FLINQ_LLM_API_KEY` / `FLINQ_LLM_MODEL` / `FLINQ_LLM_ENABLED` (all already in `core/config.py`).
- **ADR-0003 — retries**: up to 3 attempts, exponential backoff, ONLY on network errors and 5xx. Provider 4xx (bad key, bad model) fails immediately — retrying a misconfiguration is noise.
- **ADR-0003 — privacy**: raw prompt, selected text, lesson text, model response, API keys never appear in structured logs or `ai_requests`. Loggable: request_id, user_id, lesson_id, provider/model, latency, success/failure, status codes, token counts, retry count.
- **ADR-0003 — kill-switch semantics**: disabled ⇒ no external calls, no new audit rows; the product keeps working on dictionary data.
- **§11.1 — `ai_requests` is audit metadata**, not the business source of truth for translations.
- **AGENTS.md**: every AI code path degrades gracefully when disabled; AI output is always labeled AI-generated (the label itself is FLQ-5's job; this API's `hints` are the thing it labels).

Stack: Python 3.13, FastAPI, httpx (already a dependency), SQLAlchemy 2 async, loguru. No new dependencies.

## API contract

`POST /api/ai/translate` — session auth required (same `_require_user` pattern as lessons/dictionary).

Request (Pydantic, all validation → 422):

```json
{
  "surface_text": "later",              // 1..256 chars, required
  "context_text": "See you later!",     // 1..1000 chars, required
  "target_language_code": "ru",         // Literal["en", "ru", "pt"]
  "lesson_id": null                     // optional UUID, audit metadata only
}
```

Success:

```json
{
  "hints": [{"text": "позже"}, {"text": "потом"}],   // 1..3, best first
  "model": "gpt-4o-mini",
  "latency_ms": 840
}
```

Errors:

| Case | Status | Body detail |
|---|---|---|
| `FLINQ_LLM_ENABLED=false` | 503 | `ai_disabled` |
| Provider failed after retries (network, 5xx, timeout) | 502 | `ai_provider_error` |
| Provider 4xx (misconfiguration) | 502 | `ai_provider_error` |
| Model returned nothing parseable | 502 | `ai_empty_response` |
| No session | 401 — but note: a POST with no CSRF cookie/header is intercepted by `CSRFMiddleware` first and yields **403** (platform-wide behavior, same as lessons; the route's 401 fires when CSRF passes but the session is missing/invalid) | — |
| Validation (lengths, language code) | 422 | FastAPI standard |

502 bodies never include provider response text (privacy); details go to structured logs as status codes only.

## Decisions

### 1. Hints, not prose — LingQ-shaped output

The model is asked for 1–3 short translation variants of the word *as used in the given sentence*, one per line, best first — the shape of a LingQ hint list, so the Word Card can render dictionary senses and AI hints as one homogeneous list. Parsing (`parse_hints`) strips bullets/numbering/quotes, drops empties and duplicates, caps at 3. Zero parseable hints → `ai_empty_response` (502), audited as failure.

### 2. Prompt is hardcoded and deterministic

`prompts.py`, pure functions. Inputs are normalized before prompt build (NFC, strip, collapse internal whitespace runs) — this also makes `prompt_hash` stable against trivial client-side whitespace differences. Template (English instructions; target named in English):

```
system: You are a translation assistant inside a language-learning reader.
        Reply with 1 to 3 short translation variants only, one per line,
        best first. No numbering, no explanations, no quotes.
user:   Sentence: {context_text}
        Word or phrase: {surface_text}
        Translate the word or phrase as it is used in this sentence into {target_language_name}.
```

`target_language_name`: en→English, ru→Russian, pt→Portuguese. Request parameters: `temperature=0.2`, `max_tokens=100`, no JSON mode (local backends handle plain text most reliably).

### 3. Provider layer: Protocol + one httpx implementation

```python
class LLMProvider(Protocol):
    async def complete(self, *, system: str, user: str) -> LLMCompletion: ...
    # LLMCompletion: text: str, input_tokens: int | None, output_tokens: int | None
```

`OpenAICompatibleProvider(settings)` posts to `{base_url}/chat/completions` with `httpx.AsyncClient` (timeout = `llm_timeout_seconds`), `Authorization: Bearer` only when `llm_api_key` is non-empty (local backends need none). Retry loop lives here: attempts ≤ 3, backoff 0.5s → 1s, on `httpx.TransportError` and 5xx responses; anything else raises immediately. Raises typed exceptions (`ProviderUnavailable`, `ProviderRejected`) — the service maps them to 502; the provider knows nothing about HTTP status codes of *our* API.

### 4. Service orchestration and audit

`service.translate_hints(session, *, user_id, surface_text, context_text, target_language_code, lesson_id)`:
1. `settings.llm_enabled` false → raise `AIDisabled` (API → 503). Nothing logged beyond a debug line, nothing audited (ADR kill-switch semantics).
2. Normalize inputs, build prompt, compute `prompt_hash = sha256(system + "\n" + user)`, `selected_text_hash = sha256(normalized surface_text)`.
3. Call provider, measure latency.
4. Parse hints.
5. Write ONE `ai_requests` row per real provider interaction — on success (`success=true`, token counts) and on failure (`success=false`, `error_code` ∈ `provider_unavailable | provider_rejected | empty_response`), then commit. Audit failures must not mask the user-facing error: audit write is wrapped in try/`logger.exception` (lesson from FLQ-2 final review).
6. Return hints + model + latency.

No lesson-table access anywhere. `request_id` is a fresh UUID per call, echoed in structured logs for traceability.

### 5. `ai_requests` (migration 0005) — domain model §11.1 verbatim

```
ai_requests
  id UUID PK, request_id UUID, user_id UUID (FK users, ON DELETE CASCADE),
  lesson_id UUID NULL (no FK — decoupling; lessons may be deleted independently),
  item_kind text NULL, item_id UUID NULL,          -- reserved, always NULL in MVP
  provider text (host of base_url), model text,
  prompt_hash text, selected_text_hash text,
  input_tokens int NULL, output_tokens int NULL,
  latency_ms int, success bool, error_code text NULL,
  created_at timestamptz DEFAULT now()
  INDEX (user_id, created_at)                      -- future retention cleanup / per-user view
```

`user_id` cascades on user hard-delete (privacy §16); `lesson_id` deliberately has NO foreign key — the gateway must not couple to lesson lifecycle.

### 6. Error philosophy

The endpoint is interactive (card is waiting): fail fast and clean. Timeout budget = `llm_timeout_seconds` per attempt; worst case ~3 attempts on retriable failures. The card treats any 5xx as "AI unavailable" and still shows dictionary data — graceful degradation is a hard product rule.

## Module layout

```
backend/src/flinq/modules/ai_translation/
├── __init__.py     module docstring
├── provider.py     LLMProvider Protocol, LLMCompletion, OpenAICompatibleProvider, typed errors
├── prompts.py      normalize_ai_text, build_hints_prompt, parse_hints, language names
├── service.py      translate_hints orchestration + audit write
├── models.py       AIRequest
├── schemas.py      TranslateRequest, TranslateResponse, HintOut
backend/src/flinq/api/ai.py        POST /api/ai/translate (+ register in main.py)
backend/migrations/versions/0005_ai_requests.py
```

## Testing

- **provider** — `httpx.MockTransport`: success with usage fields; 500→500→200 (retry succeeds, 3rd attempt); persistent 500 → `ProviderUnavailable` after exactly 3 attempts; connect timeout → `ProviderUnavailable`; 401 from provider → `ProviderRejected` with NO retry (assert single request); no `Authorization` header when api_key empty.
- **prompts** — pure: normalization (NFC, whitespace collapse), prompt determinism (same inputs → same bytes), `parse_hints` against numbered/bulleted/quoted/duplicated/overlong model outputs, empty → `[]`.
- **service** (fake provider, real Postgres via testcontainers) — success writes one audit row with hashes + tokens + `success=true`; provider failure writes `success=false` + `error_code` and re-raises; kill-switch raises `AIDisabled` and writes NOTHING (assert zero rows); audit-write failure doesn't mask the provider result.
- **API** (ASGI, mocked provider at the service boundary) — 200 happy path with hints order preserved; 401 unauthenticated; 422 on 257-char surface / 1001-char context / bad language code; 503 when `FLINQ_LLM_ENABLED=false`; 502 with `ai_provider_error` on provider failure. AC#5 cases (mock LLM, success, timeout, provider error) all covered across these layers.
- **Privacy regression** — one test asserting the audit row contains no substring of the raw surface/context text (hashes only).

## Deferred follow-ups

- Per-user Redis cache (ADR-0003 shape) — additive, keyed on the already-stored `prompt_hash`.
- `ai_requests` retention cleanup (≤30 days recommended) — candidate for a maintenance job task.
- Admin-editable prompt template, multi-provider routing — Phase 2 (ADR-0003).
