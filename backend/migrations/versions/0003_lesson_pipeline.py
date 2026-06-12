"""lesson processing pipeline

Revision ID: 0003_lesson_pipeline
Revises: 0002_lessons_minimal
Create Date: 2026-05-31 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_lesson_pipeline"
down_revision: str | Sequence[str] | None = "0002_lessons_minimal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lessons",
        sa.Column("current_source_version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "lesson_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("license", sa.String(length=100), nullable=True),
        sa.Column("source_label", sa.String(length=200), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lesson_sources_lesson_id"), "lesson_sources", ["lesson_id"], unique=False
    )

    op.create_table(
        "lesson_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char_offset", sa.Integer(), nullable=False),
        sa.Column("end_char_offset", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "ordinal", name="uq_segment_lesson_ordinal"),
    )
    op.create_index(
        op.f("ix_lesson_segments_lesson_id"), "lesson_segments", ["lesson_id"], unique=False
    )

    op.create_table(
        "lesson_token_occurrences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("ordinal_in_lesson", sa.Integer(), nullable=False),
        sa.Column("ordinal_in_segment", sa.Integer(), nullable=False),
        sa.Column("surface_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("start_char_offset", sa.Integer(), nullable=False),
        sa.Column("end_char_offset", sa.Integer(), nullable=False),
        sa.Column("is_word_like", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["lesson_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "ordinal_in_lesson", name="uq_occurrence_lesson_ordinal"),
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_lesson_id"),
        "lesson_token_occurrences",
        ["lesson_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_segment_id"),
        "lesson_token_occurrences",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_normalized_text"),
        "lesson_token_occurrences",
        ["normalized_text"],
        unique=False,
    )

    op.create_table(
        "lesson_import_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lesson_import_jobs_lesson_id"),
        "lesson_import_jobs",
        ["lesson_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lesson_import_jobs_lesson_id"), table_name="lesson_import_jobs")
    op.drop_table("lesson_import_jobs")
    op.drop_index(
        op.f("ix_lesson_token_occurrences_normalized_text"),
        table_name="lesson_token_occurrences",
    )
    op.drop_index(
        op.f("ix_lesson_token_occurrences_segment_id"),
        table_name="lesson_token_occurrences",
    )
    op.drop_index(
        op.f("ix_lesson_token_occurrences_lesson_id"),
        table_name="lesson_token_occurrences",
    )
    op.drop_table("lesson_token_occurrences")
    op.drop_index(op.f("ix_lesson_segments_lesson_id"), table_name="lesson_segments")
    op.drop_table("lesson_segments")
    op.drop_index(op.f("ix_lesson_sources_lesson_id"), table_name="lesson_sources")
    op.drop_table("lesson_sources")
    op.drop_column("lessons", "current_source_version")
    op.drop_column("lessons", "segment_count")
