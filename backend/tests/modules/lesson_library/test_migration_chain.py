"""The pipeline migration must chain from the current head (AC#1)."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_migration_chains_from_lessons_minimal() -> None:
    # Try dotted import first; fall back to spec_from_file_location for digit-prefixed module names
    mod = None
    try:
        mod = importlib.import_module("migrations.versions.0003_lesson_pipeline")
    except (ImportError, ModuleNotFoundError):
        spec = importlib.util.spec_from_file_location(
            "0003_lesson_pipeline",
            Path(__file__).parent.parent.parent.parent
            / "migrations"
            / "versions"
            / "0003_lesson_pipeline.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

    assert mod.revision == "0003_lesson_pipeline"
    assert mod.down_revision == "0002_lessons_minimal"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
