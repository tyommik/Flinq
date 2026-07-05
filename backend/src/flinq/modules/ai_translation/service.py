"""translate_hints / translate_sentence: kill-switch -> provider -> parse -> audit.

The audit write is best-effort: its failure is logged, never masks the
user-facing result (FLQ-2 final-review lesson). Raw text never reaches
loguru or the audit table (ADR-0003).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import Settings, get_settings
from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.ai_translation.prompts import (
    build_hints_prompt,
    build_sentence_prompt,
    normalize_ai_text,
    parse_hints,
)
from flinq.modules.ai_translation.provider import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderRejected,
    ProviderUnavailable,
)


class AIDisabled(Exception):  # noqa: N818 -- name fixed by Task 5 interface contract
    """FLINQ_LLM_ENABLED is false — no calls, no audit (ADR-0003 kill-switch)."""


class AIEmptyResponse(Exception):  # noqa: N818 -- name fixed by Task 5 interface contract
    """Provider answered, but nothing parseable came back."""


@dataclass(frozen=True)
class TranslationHints:
    hints: list[str]
    model: str
    latency_ms: int


@dataclass(frozen=True)
class SentenceTranslationResult:
    text: str
    model: str
    latency_ms: int


def _default_provider() -> LLMProvider:
    return OpenAICompatibleProvider(get_settings())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _write_audit(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID | None,
    settings: Settings,
    prompt_hash: str,
    selected_text_hash: str,
    started: float,
    success: bool,
    error_code: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Shared audit-row writer for translate_hints and translate_sentence.

    Best-effort: on any failure, log and roll back so the caller's session
    stays usable — the audit write must never mask the user-facing result.
    """
    try:
        session.add(
            AIRequest(
                request_id=request_id,
                user_id=user_id,
                lesson_id=lesson_id,
                provider=urlparse(settings.llm_base_url).netloc or settings.llm_base_url,
                model=settings.llm_model,
                prompt_hash=prompt_hash,
                selected_text_hash=selected_text_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
                success=success,
                error_code=error_code,
            )
        )
        await session.commit()
    except Exception:
        logger.exception("ai_requests audit write failed (request_id={})", request_id)
        try:
            await session.rollback()
        except Exception:
            logger.exception("session rollback after failed audit write failed")


async def translate_hints(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    surface_text: str,
    context_text: str,
    target_language_code: str,
    lesson_id: uuid.UUID | None = None,
    provider: LLMProvider | None = None,
) -> TranslationHints:
    settings = get_settings()
    if not settings.llm_enabled:
        logger.debug("ai translate skipped: llm disabled")
        raise AIDisabled

    provider = provider or _default_provider()
    system, user = build_hints_prompt(
        surface_text=surface_text,
        context_text=context_text,
        target_language_code=target_language_code,
    )
    prompt_hash = _sha256(system + "\n" + user)
    selected_text_hash = _sha256(normalize_ai_text(surface_text))
    request_id = uuid.uuid4()
    started = time.monotonic()

    try:
        completion = await provider.complete(system=system, user=user)
    except ProviderUnavailable:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="provider_unavailable",
        )
        raise
    except ProviderRejected:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="provider_rejected",
        )
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    hints = parse_hints(completion.text)
    if not hints:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="empty_response",
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
        raise AIEmptyResponse
    await _write_audit(
        session,
        request_id=request_id,
        user_id=user_id,
        lesson_id=lesson_id,
        settings=settings,
        prompt_hash=prompt_hash,
        selected_text_hash=selected_text_hash,
        started=started,
        success=True,
        error_code=None,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    logger.info(
        "ai translate ok (request_id={}, latency_ms={}, hints={})",
        request_id,
        latency_ms,
        len(hints),
    )
    return TranslationHints(hints=hints, model=settings.llm_model, latency_ms=latency_ms)


async def translate_sentence(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    sentence_text: str,
    target_language_code: str,
    lesson_id: uuid.UUID | None = None,
    provider: LLMProvider | None = None,
) -> SentenceTranslationResult:
    settings = get_settings()
    if not settings.llm_enabled:
        logger.debug("ai translate sentence skipped: llm disabled")
        raise AIDisabled

    provider = provider or _default_provider()
    system, user = build_sentence_prompt(
        sentence_text=sentence_text,
        target_language_code=target_language_code,
    )
    prompt_hash = _sha256(system + "\n" + user)
    selected_text_hash = _sha256(normalize_ai_text(sentence_text))
    request_id = uuid.uuid4()
    started = time.monotonic()

    try:
        completion = await provider.complete(system=system, user=user)
    except ProviderUnavailable:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="provider_unavailable",
        )
        raise
    except ProviderRejected:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="provider_rejected",
        )
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    text = completion.text.strip()
    if not text:
        await _write_audit(
            session,
            request_id=request_id,
            user_id=user_id,
            lesson_id=lesson_id,
            settings=settings,
            prompt_hash=prompt_hash,
            selected_text_hash=selected_text_hash,
            started=started,
            success=False,
            error_code="empty_response",
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
        raise AIEmptyResponse
    await _write_audit(
        session,
        request_id=request_id,
        user_id=user_id,
        lesson_id=lesson_id,
        settings=settings,
        prompt_hash=prompt_hash,
        selected_text_hash=selected_text_hash,
        started=started,
        success=True,
        error_code=None,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    logger.info(
        "ai translate sentence ok (request_id={}, latency_ms={})",
        request_id,
        latency_ms,
    )
    return SentenceTranslationResult(text=text, model=settings.llm_model, latency_ms=latency_ms)
