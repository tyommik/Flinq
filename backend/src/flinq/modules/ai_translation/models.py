"""Metadata-only AI audit (domain model §11.1, ADR-0003 privacy rules).

Raw prompt / selected text / model response are NEVER stored here — hashes,
counts and statuses only. lesson_id deliberately has NO foreign key: the
gateway is decoupled from lesson lifecycle (spec Deviation 2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class AIRequest(Base):
    __tablename__ = "ai_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # no FK: decoupled
    item_kind: Mapped[str | None] = mapped_column(String(16))  # reserved, NULL in MVP
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # reserved
    provider: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    selected_text_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_ai_requests_user_created", "user_id", "created_at"),)
