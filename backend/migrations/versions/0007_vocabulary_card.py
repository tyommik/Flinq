"""vocabulary card annotations

Revision ID: 0007_vocabulary_card
Revises: 0006_reader_state
Create Date: 2026-07-07 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_vocabulary_card"
down_revision: str | Sequence[str] | None = "0006_reader_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_translations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("target_language_code", sa.String(length=8), nullable=False),
        sa.Column("translation_text", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_translations_item", "personal_translations",
        ["owner_user_id", "item_kind", "item_id"],
    )
    op.create_index(
        "uq_personal_translations_primary", "personal_translations",
        ["owner_user_id", "item_kind", "item_id", "target_language_code"],
        unique=True, postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "personal_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "item_kind", "item_id", name="uq_personal_notes_item"),
    )

    op.create_table(
        "item_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_name", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "item_kind", "item_id", "tag_name", name="uq_item_tags"),
    )


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_table("personal_notes")
    op.drop_index("uq_personal_translations_primary", table_name="personal_translations")
    op.drop_index("ix_personal_translations_item", table_name="personal_translations")
    op.drop_table("personal_translations")
