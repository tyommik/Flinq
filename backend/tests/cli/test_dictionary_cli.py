"""CLI wiring: pair validation and the --file path (import itself is covered in Task 5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from flinq.cli.main import app
from flinq.modules.dictionary.models import DictionarySourceVersion
from flinq.modules.dictionary.repo import DictionaryRepo

FIXTURES = Path(__file__).parents[1] / "fixtures" / "dictionary"


@pytest.fixture(autouse=True)
async def _clean_dictionary_tables(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """Real imports below hit the shared Postgres test DB (no per-test rollback);
    clear the active pt->ru version they create so it never leaks into other
    test files (see test_import_service.py for the same pattern).
    """
    yield
    await db_session.execute(delete(DictionarySourceVersion))
    await db_session.commit()


def test_unsupported_pair_without_file_errors() -> None:
    result = CliRunner().invoke(app, ["dictionary", "refresh", "--lang", "ru", "--target", "pt"])
    assert result.exit_code == 2
    assert "Unsupported pair" in result.output


async def test_run_refresh_real_body_against_test_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the REAL `_run_refresh` body (engine init / session_scope /
    dispose), not a monkeypatched replacement. `init_engine`/`dispose_engine`
    are imported inside `_run_refresh` at call time from `flinq.core.db`, so
    they must be patched there (not on `cli_dictionary`) to take effect.
    They're stubbed to no-ops because the test engine is already initialized
    by conftest, and disposing it would break every other test in the run.
    """
    import flinq.core.db as core_db
    from flinq.cli import dictionary as cli_dictionary

    def _noop_init_engine(*_args: object, **_kwargs: object) -> None:
        return None

    async def _noop_dispose_engine() -> None:
        return None

    monkeypatch.setattr(core_db, "init_engine", _noop_init_engine)
    monkeypatch.setattr(core_db, "dispose_engine", _noop_dispose_engine)

    await cli_dictionary._run_refresh("pt", "ru", FIXTURES / "ru_portuguese.jsonl", "cli-real")

    # db_session and _run_refresh's own session_scope() are separate sessions
    # on the same (already-initialized) engine; import_dump commits internally,
    # so the lookup below sees the data.
    [entry] = await DictionaryRepo(db_session).lookup(
        source_lang="pt", target_lang="ru", normalized="edifício"
    )
    assert entry.translations


def test_refresh_command_success_path_invokes_run_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the typer command's success-path wiring: arg parsing, `file:{name}`
    tag derivation, and the asyncio.run(...) bridge into `_run_refresh`.
    """
    from flinq.cli import dictionary as cli_dictionary

    calls: list[tuple[str, str, Path, str]] = []

    async def _spy(source_lang: str, target_lang: str, dump_path: Path, tag: str) -> None:
        calls.append((source_lang, target_lang, dump_path, tag))

    monkeypatch.setattr(cli_dictionary, "_run_refresh", _spy)

    fixture_path = FIXTURES / "ru_portuguese.jsonl"
    result = CliRunner().invoke(
        app,
        ["dictionary", "refresh", "--lang", "pt", "--target", "ru", "--file", str(fixture_path)],
    )

    assert result.exit_code == 0
    assert calls == [("pt", "ru", fixture_path, f"file:{fixture_path.name}")]
