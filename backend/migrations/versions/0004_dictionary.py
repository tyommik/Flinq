"""dictionary storage

Revision ID: 0004_dictionary
Revises: 0003_lesson_pipeline
Create Date: 2026-07-04 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_dictionary"
down_revision: str | Sequence[str] | None = "0003_lesson_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dictionary_source_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_language_code", sa.String(length=8), nullable=False),
        sa.Column("target_language_code", sa.String(length=8), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_dictionary_versions_active_pair",
        "dictionary_source_versions",
        ["source_language_code", "target_language_code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "dictionary_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_version_id", sa.UUID(), nullable=False),
        sa.Column("source_language_code", sa.String(length=8), nullable=False),
        sa.Column("headword", sa.Text(), nullable=False),
        sa.Column("headword_normalized", sa.Text(), nullable=False),
        sa.Column("part_of_speech", sa.String(length=32), nullable=True),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("gloss_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["dictionary_source_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "entry_key", name="uq_dictionary_entries_key"),
    )
    op.create_index(
        "ix_dictionary_entries_lookup",
        "dictionary_entries",
        ["source_language_code", "headword_normalized", "source_version_id"],
        unique=False,
    )

    op.create_table(
        "dictionary_translations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("target_language_code", sa.String(length=8), nullable=False),
        sa.Column("translation_text", sa.Text(), nullable=False),
        sa.Column("sense_index", sa.Integer(), nullable=False),
        sa.Column("usage_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["entry_id"], ["dictionary_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dictionary_translations_entry_id"),
        "dictionary_translations",
        ["entry_id"],
        unique=False,
    )

    op.create_table(
        "dictionary_examples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("sense_index", sa.Integer(), nullable=False),
        sa.Column("example_text", sa.Text(), nullable=False),
        sa.Column("example_translation", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["entry_id"], ["dictionary_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dictionary_examples_entry_id"),
        "dictionary_examples",
        ["entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dictionary_examples_entry_id"), table_name="dictionary_examples")
    op.drop_table("dictionary_examples")
    op.drop_index(op.f("ix_dictionary_translations_entry_id"), table_name="dictionary_translations")
    op.drop_table("dictionary_translations")
    op.drop_index("ix_dictionary_entries_lookup", table_name="dictionary_entries")
    op.drop_table("dictionary_entries")
    op.drop_index("uq_dictionary_versions_active_pair", table_name="dictionary_source_versions")
    op.drop_table("dictionary_source_versions")
