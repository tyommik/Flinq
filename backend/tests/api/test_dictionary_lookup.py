"""GET /api/dictionary/lookup — AC#3, AC#5 and spec Decision 6."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.main import create_app
from flinq.modules.dictionary import service
from flinq.modules.dictionary.models import DictionarySourceVersion

FIXTURES = Path(__file__).parents[1] / "fixtures" / "dictionary"


@pytest.fixture(autouse=True)
async def _clean_dictionary_tables(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """Each test hits a real, shared Postgres (no per-test rollback), and
    `DictionarySourceVersion` rows cascade-delete their entries/translations/
    examples. Clear them after every test so this file never leaks active
    versions into other test files (or between its own tests).
    """
    yield
    await db_session.execute(delete(DictionarySourceVersion))
    await db_session.commit()


async def _register_and_onboard(c: AsyncClient, email: str, lang: str = "pt") -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={"ui_language": "en", "learning_languages": [lang], "translation_language": "en"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


async def _seed(db_session: AsyncSession) -> None:
    await service.import_dump(
        db_session,
        source_lang="en",
        target_lang="ru",
        dump_path=FIXTURES / "en_english.jsonl",
        source_version_tag="t",
    )
    await service.import_dump(
        db_session,
        source_lang="ru",
        target_lang="en",
        dump_path=FIXTURES / "en_russian.jsonl",
        source_version_tag="t",
    )
    await service.import_dump(
        db_session,
        source_lang="pt",
        target_lang="ru",
        dump_path=FIXTURES / "ru_portuguese.jsonl",
        source_version_tag="t",
    )


async def test_lookup_en_ru_ru_en_pt_ru(db_session: AsyncSession) -> None:
    await _seed(db_session)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "dict-lookup@example.com")

        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "Building"}
        )
        assert r.status_code == 200
        body = r.json()
        [entry] = body["entries"]
        assert entry["headword"] == "building"
        assert {s["translation"] for s in entry["senses"]} == {"здание", "строение"}
        assert body["attribution"]["license"] == "CC-BY-SA 4.0"
        assert any(link["name"] == "Lingvo Live" for link in body["external_links"])

        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "ru", "target": "en", "text": "дом"}
        )
        assert r.json()["entries"][0]["senses"][0]["translation"] == "house; building"

        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "pt", "target": "ru", "text": "edifício"}
        )
        assert r.json()["entries"][0]["senses"][0]["translation"] == "здание; строение"


async def test_unknown_word_and_uncovered_pair_return_200_empty(db_session: AsyncSession) -> None:
    await _seed(db_session)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "dict-empty@example.com")
        for params in (
            {"lang": "en", "target": "ru", "text": "zzzznope"},
            {"lang": "ru", "target": "pt", "text": "дом"},  # valid but uncovered pair
        ):
            r = await c.get("/api/dictionary/lookup", params=params)
            assert r.status_code == 200
            body = r.json()
            assert body["entries"] == []
            assert body["external_links"]
            assert body["attribution"]["license"] == "CC-BY-SA 4.0"


async def test_validation_and_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "x"}
        )
        assert r.status_code == 401  # no session

        await _register_and_onboard(c, "dict-auth@example.com")
        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "xx", "target": "ru", "text": "x"}
        )
        assert r.status_code == 422  # bad language code
        r = await c.get(
            "/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "y" * 300}
        )
        assert r.status_code == 422  # text too long
