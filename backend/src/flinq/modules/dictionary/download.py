"""Dump download and reading — the only I/O in the import path."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path

import httpx
from loguru import logger

_PROGRESS_EVERY_BYTES = 50 * 1024 * 1024


async def download_dump(
    url: str, dest_dir: Path, *, client: httpx.AsyncClient | None = None
) -> Path:
    """Stream `url` into `dest_dir/<filename>` with progress logs; return the path."""
    dest_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 -- one-off dir create, not hot path
    dest = dest_dir / url.rsplit("/", 1)[-1]
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0))
    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            done = 0
            next_mark = _PROGRESS_EVERY_BYTES
            with dest.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        logger.info("dictionary download: {} MB", done // (1024 * 1024))
                        next_mark += _PROGRESS_EVERY_BYTES
    finally:
        if own_client:
            await client.aclose()
    logger.info("dictionary download finished: {} ({} bytes)", dest, dest.stat().st_size)
    return dest


def iter_dump_lines(path: Path) -> Iterator[str]:
    """Yield lines from a plain or gzip JSONL file."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            yield from f
    else:
        with path.open("rt", encoding="utf-8") as f:
            yield from f
