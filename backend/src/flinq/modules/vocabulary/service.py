"""Vocabulary WordCard service (FLQ-5). Session-first module functions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.textnorm import normalize_token
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


class UnsupportedKind(Exception):  # noqa: N818 -- name fixed by Task 2 interface contract
    """Only 'token' is supported in Increment 1."""


class ItemNotFound(Exception):  # noqa: N818 -- name fixed by Task 2 interface contract
    """Item does not exist or is not owned by the user."""


class TranslationNotFound(Exception):  # noqa: N818 -- matches sibling exception naming
    """Translation row does not exist or is not owned by the user/item."""


class DuplicateTranslation(Exception):  # noqa: N818 -- matches sibling exception naming
    """Another variant with the same text exists for this item/target."""


@dataclass
class LookupResult:
    item_id: uuid.UUID | None
    status: str
    confidence: int | None
    translations: list[PersonalTranslation]
    primary: PersonalTranslation | None
    note: str | None
    tags: list[str] = field(default_factory=list)


def _check_kind(kind: str) -> None:
    if kind != "token":
        raise UnsupportedKind(kind)


async def _get_token_item(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str
) -> TokenItem | None:
    stmt = select(TokenItem).where(
        TokenItem.user_id == user_id,
        TokenItem.language_code == language_code,
        TokenItem.token_text == text,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _owned_item(
    session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID
) -> TokenItem:
    item = await session.get(TokenItem, item_id)
    if item is None or item.user_id != user_id:
        raise ItemNotFound(str(item_id))
    return item


async def create_item(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    language_code: str,
    text: str,
    status: str,
    confidence: int | None,
) -> TokenItem:
    _check_kind(kind)
    normalized = normalize_token(text)
    existing = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if existing is not None:
        existing.status = status
        existing.confidence = confidence
        await session.commit()
        return existing
    item = TokenItem(
        user_id=user_id,
        language_code=language_code,
        token_text=normalized,
        status=status,
        confidence=confidence,
    )
    session.add(item)
    await session.commit()
    return item


async def patch_item(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    status: str,
    confidence: int | None,
) -> TokenItem:
    _check_kind(kind)
    item = await _owned_item(session, user_id=user_id, item_id=item_id)
    item.status = status
    item.confidence = confidence
    await session.commit()
    return item


async def _list_tags(session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(ItemTag.tag_name)
                .where(
                    ItemTag.owner_user_id == user_id,
                    ItemTag.item_kind == "token",
                    ItemTag.item_id == item_id,
                )
                .order_by(ItemTag.tag_name)
            )
        )
        .scalars()
        .all()
    )


async def _owned_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
) -> PersonalTranslation:
    row = await session.get(PersonalTranslation, translation_id)
    if row is None or row.owner_user_id != user_id or row.item_id != item_id:
        raise TranslationNotFound(str(translation_id))
    return row


async def _item_translations(
    session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID
) -> list[PersonalTranslation]:
    return list(
        (
            await session.execute(
                select(PersonalTranslation)
                .where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id == item_id,
                )
                .order_by(PersonalTranslation.is_primary.desc(), PersonalTranslation.created_at)
            )
        )
        .scalars()
        .all()
    )


async def lookup(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    language_code: str,
    text: str,
    target_language_code: str,
) -> LookupResult:
    normalized = normalize_token(text)
    item = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if item is None:
        return LookupResult(
            item_id=None,
            status="new",
            confidence=None,
            translations=[],
            primary=None,
            note=None,
            tags=[],
        )
    translations = await _item_translations(session, user_id=user_id, item_id=item.id)
    primary = next(
        (
            t
            for t in translations
            if t.is_primary and t.target_language_code == target_language_code
        ),
        None,
    )
    note_row = (
        await session.execute(
            select(PersonalNote).where(
                PersonalNote.owner_user_id == user_id,
                PersonalNote.item_kind == "token",
                PersonalNote.item_id == item.id,
            )
        )
    ).scalar_one_or_none()
    tags = await _list_tags(session, user_id=user_id, item_id=item.id)
    return LookupResult(
        item_id=item.id,
        status=item.status,
        confidence=item.confidence,
        translations=translations,
        primary=primary,
        note=note_row.note_text if note_row else None,
        tags=tags,
    )


async def add_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    target_language_code: str,
    translation_text: str,
    source_type: str,
) -> tuple[PersonalTranslation, bool]:
    """Add a variant; returns (row, created).

    Dedupes by exact text: an existing row with the same text is returned
    as-is (created=False). `is_primary` is computed server-side — the first
    variant for the (owner, item, target) becomes primary (§2.2 of the spec).
    """
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    scope = (
        PersonalTranslation.owner_user_id == user_id,
        PersonalTranslation.item_kind == "token",
        PersonalTranslation.item_id == item_id,
        PersonalTranslation.target_language_code == target_language_code,
    )
    existing = (
        await session.execute(
            select(PersonalTranslation).where(
                *scope, PersonalTranslation.translation_text == translation_text
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    has_any = (
        await session.execute(select(PersonalTranslation.id).where(*scope).limit(1))
    ).scalar_one_or_none() is not None
    row = PersonalTranslation(
        owner_user_id=user_id,
        item_kind="token",
        item_id=item_id,
        target_language_code=target_language_code,
        translation_text=translation_text,
        is_primary=not has_any,
        source_type=source_type,
    )
    session.add(row)
    await session.commit()
    return row, True


async def update_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    translation_text: str,
) -> PersonalTranslation:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    row = await _owned_translation(
        session, user_id=user_id, item_id=item_id, translation_id=translation_id
    )
    if row.translation_text == translation_text:
        return row
    duplicate = (
        await session.execute(
            select(PersonalTranslation.id).where(
                PersonalTranslation.owner_user_id == user_id,
                PersonalTranslation.item_kind == "token",
                PersonalTranslation.item_id == item_id,
                PersonalTranslation.target_language_code == row.target_language_code,
                PersonalTranslation.translation_text == translation_text,
                PersonalTranslation.id != row.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise DuplicateTranslation(translation_text)
    row.translation_text = translation_text
    row.source_type = "user"
    await session.commit()
    return row


async def delete_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
) -> list[PersonalTranslation]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    row = await _owned_translation(
        session, user_id=user_id, item_id=item_id, translation_id=translation_id
    )
    was_primary = row.is_primary
    target = row.target_language_code
    await session.delete(row)
    await session.flush()
    if was_primary:
        successor = (
            await session.execute(
                select(PersonalTranslation)
                .where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id == item_id,
                    PersonalTranslation.target_language_code == target,
                )
                .order_by(PersonalTranslation.created_at, PersonalTranslation.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if successor is not None:
            successor.is_primary = True
    await session.commit()
    return await _item_translations(session, user_id=user_id, item_id=item_id)


async def put_note(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    note_text: str,
) -> PersonalNote:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    stmt = (
        pg_insert(PersonalNote)
        .values(
            id=uuid.uuid4(),
            owner_user_id=user_id,
            item_kind="token",
            item_id=item_id,
            note_text=note_text,
        )
        .on_conflict_do_update(constraint="uq_personal_notes_item", set_={"note_text": note_text})
        .returning(PersonalNote)
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return row


async def add_tag(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    tag_name: str,
) -> list[str]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    await session.execute(
        pg_insert(ItemTag)
        .values(
            id=uuid.uuid4(),
            owner_user_id=user_id,
            item_kind="token",
            item_id=item_id,
            tag_name=tag_name,
        )
        .on_conflict_do_nothing(constraint="uq_item_tags")
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, item_id=item_id)


async def remove_tag(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    tag_name: str,
) -> list[str]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    await session.execute(
        delete(ItemTag).where(
            ItemTag.owner_user_id == user_id,
            ItemTag.item_kind == "token",
            ItemTag.item_id == item_id,
            ItemTag.tag_name == tag_name,
        )
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, item_id=item_id)
