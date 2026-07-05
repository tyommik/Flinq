"""The one OpenAI-compatible LLM adapter (ADR-0003). Only HTTP-facing layer.

Retry discipline: up to 3 attempts, exponential backoff, ONLY on transport
errors and 5xx. Provider 4xx (bad key/model) fails immediately. Privacy:
never log message contents — status codes and attempt counts only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx
from loguru import logger

from flinq.core.config import Settings

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5


class ProviderUnavailable(Exception):  # noqa: N818 -- name fixed by ADR-0003 interface contract
    """Network failure, timeout or 5xx after all retries."""


class ProviderRejected(Exception):  # noqa: N818 -- name fixed by ADR-0003 interface contract
    """Non-retriable provider response (4xx or malformed body)."""


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    input_tokens: int | None
    output_tokens: int | None


class LLMProvider(Protocol):
    async def complete(self, *, system: str, user: str) -> LLMCompletion: ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        s = self._settings
        payload = {
            "model": s.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 100,
        }
        headers: dict[str, str] = {}
        if s.llm_api_key:
            headers["Authorization"] = f"Bearer {s.llm_api_key}"
        url = f"{s.llm_base_url.rstrip('/')}/chat/completions"

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=float(s.llm_timeout_seconds))
        try:
            last_error: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    last_error = exc
                    logger.warning(
                        "llm attempt {}/{}: {}", attempt, _MAX_ATTEMPTS, type(exc).__name__
                    )
                else:
                    if response.status_code < 400:
                        return _parse_completion(response)
                    if response.status_code < 500:
                        raise ProviderRejected(f"provider returned {response.status_code}")
                    last_error = ProviderUnavailable(f"provider returned {response.status_code}")
                    logger.warning(
                        "llm attempt {}/{}: HTTP {}", attempt, _MAX_ATTEMPTS, response.status_code
                    )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            raise ProviderUnavailable(str(last_error)) from last_error
        finally:
            if own_client:
                await client.aclose()


def _parse_completion(response: httpx.Response) -> LLMCompletion:
    try:
        body = response.json()
        text = body["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderRejected("malformed provider response") from exc
    usage = body.get("usage") or {}
    return LLMCompletion(
        text=text,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )
