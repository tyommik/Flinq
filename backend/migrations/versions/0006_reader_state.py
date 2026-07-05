"""reader state

Revision ID: 0006_reader_state
Revises: 0005_ai_requests
Create Date: 2026-07-05 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_reader_state"
down_revision: str | Sequence[str] | None = "0005_ai_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=8), nullable=False),
        sa.Column("token_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("created_from_occurrence_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "language_code", "token_text", name="uq_token_items_user_lang_text"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_token_items_confidence_range",
        ),
        sa.CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_token_items_confidence_tracked",
        ),
    )
    op.create_index("ix_token_items_user_lang", "token_items", ["user_id", "language_code"])

    op.create_table(
        "reader_positions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("view_mode", sa.String(length=16), nullable=False),
        sa.Column("current_segment_id", sa.UUID(), nullable=True),
        sa.Column("current_token_ordinal", sa.Integer(), nullable=True),
        sa.Column(
            "last_opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_reader_positions_user_lesson"),
    )

    op.create_table(
        "bulk_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("page_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lesson_segment_translations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("target_language_code", sa.String(length=8), nullable=False),
        sa.Column("translation_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["segment_id"], ["lesson_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "segment_id", "target_language_code", name="uq_segment_translation_lang"
        ),
    )


def downgrade() -> None:
    op.drop_table("lesson_segment_translations")
    op.drop_table("bulk_actions")
    op.drop_table("reader_positions")
    op.drop_index("ix_token_items_user_lang", table_name="token_items")
    op.drop_table("token_items")
