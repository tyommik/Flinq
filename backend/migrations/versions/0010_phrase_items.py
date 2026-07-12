"""phrase items

Revision ID: 0010_phrase_items
Revises: 0009_item_provenance
Create Date: 2026-07-12 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_phrase_items"
down_revision: str | Sequence[str] | None = "0009_item_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phrase_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("language_code", sa.String(length=8), nullable=False),
        sa.Column("phrase_text", sa.Text(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column(
            "added_by", sa.String(length=16), server_default="user", nullable=False
        ),
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
            "user_id", "language_code", "phrase_text", name="uq_phrase_items_user_lang_text"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_phrase_items_confidence_range",
        ),
        sa.CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_phrase_items_confidence_tracked",
        ),
        sa.CheckConstraint("added_by IN ('user', 'bulk')", name="ck_phrase_items_added_by"),
        sa.CheckConstraint(
            "array_length(string_to_array(phrase_text, ' '), 1) BETWEEN 2 AND 8",
            name="ck_phrase_items_word_count",
        ),
    )
    op.create_index("ix_phrase_items_user_lang", "phrase_items", ["user_id", "language_code"])


def downgrade() -> None:
    # Satellite tables reference phrase items only by (item_kind, item_id) —
    # no FK — so dropping phrase_items would orphan their 'phrase' rows.
    op.execute(sa.text("DELETE FROM personal_translations WHERE item_kind = 'phrase'"))
    op.execute(sa.text("DELETE FROM personal_notes WHERE item_kind = 'phrase'"))
    op.execute(sa.text("DELETE FROM item_tags WHERE item_kind = 'phrase'"))
    op.drop_index("ix_phrase_items_user_lang", table_name="phrase_items")
    op.drop_table("phrase_items")
