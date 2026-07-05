"""ai_requests audit

Revision ID: 0005_ai_requests
Revises: 0004_dictionary
Create Date: 2026-07-05 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ai_requests"
down_revision: str | Sequence[str] | None = "0004_dictionary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=True),
        sa.Column("item_kind", sa.String(length=16), nullable=True),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("selected_text_hash", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_requests_user_created", "ai_requests", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_requests_user_created", table_name="ai_requests")
    op.drop_table("ai_requests")
