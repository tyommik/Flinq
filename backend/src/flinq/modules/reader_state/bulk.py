"""Bulk-known + undo (spec ADR-0005): mark new words in an ordinal range known.

Only words with NO existing TokenItem for the user get a `known` row —
`tracked`/`known`/`ignored` items are left untouched. The insert uses
client-side UUIDs with `ON CONFLICT DO NOTHING` + `RETURNING` so the action
payload lists only the ids genuinely created here, which is exactly what
undo needs to reverse the action without touching anything else.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson, LessonTokenOccurrence
from flinq.modules.reader_state.models import BulkAction
from flinq.modules.vocabulary.models import TokenItem


class ActionNotFound(Exception): ...  # noqa: N818 — mapped to 404 by the router


class ActionAlreadyUndone(Exception): ...  # noqa: N818 — mapped to 409 by the router


async def bulk_mark_known(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    lesson: Lesson,
    from_ordinal: int,
    to_ordinal: int,
) -> tuple[uuid.UUID, int]:
    texts = set(
        await session.scalars(
            select(LessonTokenOccurrence.normalized_text)
            .distinct()
            .where(
                LessonTokenOccurrence.lesson_id == lesson.id,
                LessonTokenOccurrence.is_word_like.is_(True),
                LessonTokenOccurrence.ordinal_in_lesson.between(from_ordinal, to_ordinal),
            )
        )
    )
    if texts:
        stmt = (
            pg_insert(TokenItem)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "language_code": lesson.language_code,
                        "token_text": t,
                        "status": "known",
                        "confidence": None,
                        "added_by": "bulk",
                    }
                    for t in sorted(texts)
                ]
            )
            .on_conflict_do_nothing(constraint="uq_token_items_user_lang_text")
            .returning(TokenItem.id)
        )
        created_ids = list((await session.execute(stmt)).scalars().all())
    else:
        created_ids = []

    action = BulkAction(
        user_id=user_id,
        lesson_id=lesson.id,
        action_type="bulk_known",
        page_fingerprint=f"{from_ordinal}:{to_ordinal}",
        payload_json={"token_item_ids": [str(i) for i in created_ids]},
    )
    session.add(action)
    await session.commit()
    return action.id, len(created_ids)


async def undo_bulk_action(
    session: AsyncSession, *, user_id: uuid.UUID, action_id: uuid.UUID
) -> int:
    action = await session.get(BulkAction, action_id)
    if action is None or action.user_id != user_id:
        raise ActionNotFound
    if action.undone_at is not None:
        raise ActionAlreadyUndone
    ids = [uuid.UUID(x) for x in action.payload_json.get("token_item_ids", [])]
    undone = 0
    if ids:
        result = await session.execute(
            delete(TokenItem)
            .where(
                TokenItem.id.in_(ids),
                TokenItem.status == "known",
                TokenItem.added_by == "bulk",
            )
            .returning(TokenItem.id)
        )
        undone = len(list(result.scalars().all()))
    action.undone_at = func.now()
    await session.commit()
    return undone
