"""translation variants: dedupe exact duplicates, unique text per item/target

Revision ID: 0008_translation_variants
Revises: 0007_vocabulary_card
Create Date: 2026-07-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_translation_variants"
down_revision: str | Sequence[str] | None = "0007_vocabulary_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Data fix: drop exact duplicates, keeping the primary row if any,
    # otherwise the earliest. Must run before the unique index lands.
    op.execute(
        sa.text(
            """
            DELETE FROM personal_translations pt
            USING (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY owner_user_id, item_kind, item_id,
                                        target_language_code, translation_text
                           ORDER BY is_primary DESC, created_at ASC, id ASC
                       ) AS rn
                FROM personal_translations
            ) ranked
            WHERE pt.id = ranked.id AND ranked.rn > 1
            """
        )
    )
    op.create_index(
        "uq_personal_translations_text",
        "personal_translations",
        ["owner_user_id", "item_kind", "item_id", "target_language_code", "translation_text"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_personal_translations_text", table_name="personal_translations")
