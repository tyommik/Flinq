"""`flinq dictionary` commands (ADR-0004: manual admin refresh)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer
from loguru import logger

app = typer.Typer(help="Built-in dictionary data management.")


async def _run_refresh(source_lang: str, target_lang: str, dump_path: Path, tag: str) -> None:
    from flinq.core.config import get_settings
    from flinq.core.db import dispose_engine, init_engine, session_scope
    from flinq.modules.dictionary.service import import_dump

    init_engine(get_settings())
    try:
        async with session_scope() as session:
            stats = await import_dump(
                session,
                source_lang=source_lang,
                target_lang=target_lang,
                dump_path=dump_path,
                source_version_tag=tag,
            )
        logger.info("refresh complete: {}", stats)
    finally:
        await dispose_engine()


@app.command()
def refresh(
    lang: str = typer.Option(..., help="Source language code (en|ru|pt)."),
    target: str = typer.Option(..., help="Target language code (en|ru|pt)."),
    file: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="Local JSONL[.gz] dump instead of downloading."
    ),
) -> None:
    """Download (or read --file) a Kaikki dump and load it into Postgres."""
    from flinq.core.config import get_settings
    from flinq.modules.dictionary.download import download_dump
    from flinq.modules.dictionary.sources import DUMP_SOURCES

    source = DUMP_SOURCES.get((lang, target))
    if source is None and file is None:
        supported = ", ".join(f"{s}->{t}" for s, t in sorted(DUMP_SOURCES))
        typer.echo(f"Unsupported pair {lang}->{target}. Supported: {supported}", err=True)
        raise typer.Exit(2)

    async def _main() -> None:
        if file is not None:
            dump_path, tag = file, f"file:{file.name}"
        else:
            assert source is not None
            cache = get_settings().data_dir / "dictionary-dumps"
            dump_path = await download_dump(source.url, cache)
            tag = f"{dump_path.name}@{datetime.now(UTC).date().isoformat()}"
        await _run_refresh(lang, target, dump_path, tag)

    asyncio.run(_main())
