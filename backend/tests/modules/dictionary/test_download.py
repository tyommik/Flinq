"""Streaming download + gzip-aware line iteration."""

from __future__ import annotations

import gzip
from pathlib import Path

import httpx

from flinq.modules.dictionary.download import download_dump, iter_dump_lines
from flinq.modules.dictionary.sources import DUMP_SOURCES


def test_registry_covers_the_five_pairs() -> None:
    assert set(DUMP_SOURCES) == {
        ("en", "ru"),
        ("en", "pt"),
        ("ru", "en"),
        ("pt", "en"),
        ("pt", "ru"),
    }


async def test_download_streams_to_file(tmp_path: Path) -> None:
    body = b'{"word": "a"}\n{"word": "b"}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    path = await download_dump("https://example.org/dump.jsonl", tmp_path, client=client)
    assert path == tmp_path / "dump.jsonl"
    assert path.read_bytes() == body


def test_iter_dump_lines_plain_and_gzip(tmp_path: Path) -> None:
    plain = tmp_path / "d.jsonl"
    plain.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    gz = tmp_path / "d.jsonl.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.write('{"a": 1}\n{"b": 2}\n')
    assert list(iter_dump_lines(plain)) == list(iter_dump_lines(gz)) == ['{"a": 1}\n', '{"b": 2}\n']
