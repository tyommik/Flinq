"""Per-user vocabulary items (domain model §8.2).

`token_text` is stored ALREADY NORMALIZED (flinq.core.textnorm.normalize_token
output) — it is the join key to lesson occurrences and dictionary headwords.
No FK to occurrences (§2.4): the link is computed by
(user_id, lesson.language_code, normalized_text).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class TokenItem(Base):
    __tablename__ = "token_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str] = mapped_column(String(8))
    token_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # tracked | known | ignored ('new' is computed)
    confidence: Mapped[int | None] = mapped_column(Integer)
    created_from_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "language_code", "token_text", name="uq_token_items_user_lang_text"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_token_items_confidence_range",
        ),
        CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_token_items_confidence_tracked",
        ),
        Index("ix_token_items_user_lang", "user_id", "language_code"),
    )
