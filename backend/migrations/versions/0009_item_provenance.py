"""token item provenance: added_by user|bulk with bulk-known backfill

Revision ID: 0009_item_provenance
Revises: 0008_translation_variants
Create Date: 2026-07-11 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_item_provenance"
down_revision: str | Sequence[str] | None = "0008_translation_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "token_items",
        sa.Column("added_by", sa.String(length=16), nullable=False, server_default="user"),
    )
    op.create_check_constraint(
        "ck_token_items_added_by", "token_items", "added_by IN ('user', 'bulk')"
    )
    # Backfill: items created by page-turn bulk-known actions (FLQ-4) are
    # provenance 'bulk'. bulk_actions.payload_json->'token_item_ids' lists
    # exactly the ids each action created (reader_state/bulk.py); undone
    # actions already deleted their rows, so the update is a no-op for them.
    op.execute(
        sa.text(
            """
            UPDATE token_items
            SET added_by = 'bulk'
            WHERE id IN (
                SELECT (jsonb_array_elements_text(payload_json->'token_item_ids'))::uuid
                FROM bulk_actions
                WHERE action_type = 'bulk_known' AND undone_at IS NULL
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_token_items_added_by", "token_items", type_="check")
    op.drop_column("token_items", "added_by")
