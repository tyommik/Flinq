"""Schema-level checks for the lesson pipeline tables (AC#1, AC#5)."""

from __future__ import annotations

from sqlalchemy import inspect

from flinq.core.db import get_engine


async def test_pipeline_tables_exist() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {
        "lesson_sources",
        "lesson_segments",
        "lesson_token_occurrences",
        "lesson_import_jobs",
    } <= tables


async def test_lessons_has_new_columns() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("lessons")}
        )
    assert "segment_count" in cols
    assert "current_source_version" in cols


async def test_occurrence_unique_constraint() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        uniques = await conn.run_sync(
            lambda c: {
                uc["name"] for uc in inspect(c).get_unique_constraints("lesson_token_occurrences")
            }
        )
    assert "uq_occurrence_lesson_ordinal" in uniques
