"""phrase_text structural check (2..8 non-space words, single spaces)

Revision ID: 0011_phrase_text_check
Revises: 0010_phrase_items
Create Date: 2026-07-12 00:00:00.000000

The old array_length check counted space-separated chunks, so strings of
bare spaces (empty "words", e.g. phrase_text = ' ') passed as 2 words.
The regex check requires 2..8 runs of non-space characters joined by
single spaces, which structurally excludes empties.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_phrase_text_check"
down_revision: str | Sequence[str] | None = "0010_phrase_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_phrase_items_word_count", "phrase_items", type_="check")
    op.create_check_constraint(
        "ck_phrase_items_word_count",
        "phrase_items",
        r"phrase_text ~ '^\S+( \S+){1,7}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_phrase_items_word_count", "phrase_items", type_="check")
    op.create_check_constraint(
        "ck_phrase_items_word_count",
        "phrase_items",
        "array_length(string_to_array(phrase_text, ' '), 1) BETWEEN 2 AND 8",
    )
