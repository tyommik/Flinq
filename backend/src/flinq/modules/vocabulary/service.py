"""Vocabulary WordCard service (FLQ-5). Session-first module functions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, and_, delete, exists, func, literal, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.textnorm import normalize_token
from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
from flinq.modules.lesson_library.tokenization import normalize_phrase
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)

VocabItem = TokenItem | PhraseItem

_MODEL_BY_KIND: dict[str, type[TokenItem] | type[PhraseItem]] = {
    "token": TokenItem,
    "phrase": PhraseItem,
}


class UnsupportedKind(Exception):  # noqa: N818 -- name fixed by Task 2 interface contract
    """Kind is not one of 'token' | 'phrase'."""


class ItemNotFound(Exception):  # noqa: N818 -- name fixed by Task 2 interface contract
    """Item does not exist or is not owned by the user."""


class TranslationNotFound(Exception):  # noqa: N818 -- matches sibling exception naming
    """Translation row does not exist or is not owned by the user/item."""


class DuplicateTranslation(Exception):  # noqa: N818 -- matches sibling exception naming
    """Another variant with the same text exists for this item/target."""


class InvalidPhrase(Exception):  # noqa: N818 -- matches sibling exception naming
    """Phrase text has fewer than 2 or more than 8 word tokens."""


@dataclass
class LookupResult:
    item_id: uuid.UUID | None
    status: str
    confidence: int | None
    translations: list[PersonalTranslation]
    primary: PersonalTranslation | None
    note: str | None
    tags: list[str] = field(default_factory=list)


@dataclass
class VocabListItem:
    item_id: uuid.UUID
    kind: str
    text: str
    status: str
    confidence: int | None
    primary_translation_text: str | None
    primary_translation_target: str | None
    tags: list[str] = field(default_factory=list)
    pos: str | None = None
    context: str | None = None
    created_at: datetime | None = None


def _check_kind(kind: str) -> None:
    if kind not in _MODEL_BY_KIND:
        raise UnsupportedKind(kind)


def _promote_to_user(item: VocabItem) -> None:
    """Explicit user action on a bulk-created item claims it (spec FLQ-6.2 §1.2)."""
    if item.added_by != "user":
        item.added_by = "user"


async def _get_token_item(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str
) -> TokenItem | None:
    stmt = select(TokenItem).where(
        TokenItem.user_id == user_id,
        TokenItem.language_code == language_code,
        TokenItem.token_text == text,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _get_phrase_item(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str
) -> PhraseItem | None:
    stmt = select(PhraseItem).where(
        PhraseItem.user_id == user_id,
        PhraseItem.language_code == language_code,
        PhraseItem.phrase_text == text,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _owned_item(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> VocabItem:
    item = await session.get(_MODEL_BY_KIND[kind], item_id)
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
) -> VocabItem:
    _check_kind(kind)
    if kind == "phrase":
        normalized = normalize_phrase(text)
        word_count = len(normalized.split(" ")) if normalized else 0
        if not 2 <= word_count <= 8:
            raise InvalidPhrase(text)
        existing_phrase = await _get_phrase_item(
            session, user_id=user_id, language_code=language_code, text=normalized
        )
        if existing_phrase is not None:
            existing_phrase.status = status
            existing_phrase.confidence = confidence
            _promote_to_user(existing_phrase)
            await session.commit()
            return existing_phrase
        phrase = PhraseItem(
            user_id=user_id,
            language_code=language_code,
            phrase_text=normalized,
            display_text=text.strip(),
            status=status,
            confidence=confidence,
            added_by="user",
        )
        session.add(phrase)
        await session.commit()
        return phrase
    normalized = normalize_token(text)
    existing = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if existing is not None:
        existing.status = status
        existing.confidence = confidence
        _promote_to_user(existing)
        await session.commit()
        return existing
    item = TokenItem(
        user_id=user_id,
        language_code=language_code,
        token_text=normalized,
        status=status,
        confidence=confidence,
        added_by="user",
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
) -> VocabItem:
    _check_kind(kind)
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    item.status = status
    item.confidence = confidence
    _promote_to_user(item)
    await session.commit()
    return item


async def _list_tags(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> list[str]:
    return list(
        (
            await session.execute(
                select(ItemTag.tag_name)
                .where(
                    ItemTag.owner_user_id == user_id,
                    ItemTag.item_kind == kind,
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
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> list[PersonalTranslation]:
    return list(
        (
            await session.execute(
                select(PersonalTranslation)
                .where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == kind,
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
    kind: str = "token",
) -> LookupResult:
    _check_kind(kind)
    if kind == "phrase":
        normalized = normalize_phrase(text)
        item: VocabItem | None = await _get_phrase_item(
            session, user_id=user_id, language_code=language_code, text=normalized
        )
    else:
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
    translations = await _item_translations(session, user_id=user_id, kind=kind, item_id=item.id)
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
                PersonalNote.item_kind == kind,
                PersonalNote.item_id == item.id,
            )
        )
    ).scalar_one_or_none()
    tags = await _list_tags(session, user_id=user_id, kind=kind, item_id=item.id)
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
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
    scope = (
        PersonalTranslation.owner_user_id == user_id,
        PersonalTranslation.item_kind == kind,
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
        item_kind=kind,
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
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
    row = await _owned_translation(
        session, user_id=user_id, item_id=item_id, translation_id=translation_id
    )
    if row.translation_text == translation_text:
        return row
    duplicate = (
        await session.execute(
            select(PersonalTranslation.id).where(
                PersonalTranslation.owner_user_id == user_id,
                PersonalTranslation.item_kind == kind,
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
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
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
                    PersonalTranslation.item_kind == kind,
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
    return await _item_translations(session, user_id=user_id, kind=kind, item_id=item_id)


async def put_note(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    note_text: str,
) -> PersonalNote:
    _check_kind(kind)
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
    stmt = (
        pg_insert(PersonalNote)
        .values(
            id=uuid.uuid4(),
            owner_user_id=user_id,
            item_kind=kind,
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
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
    await session.execute(
        pg_insert(ItemTag)
        .values(
            id=uuid.uuid4(),
            owner_user_id=user_id,
            item_kind=kind,
            item_id=item_id,
            tag_name=tag_name,
        )
        .on_conflict_do_nothing(constraint="uq_item_tags")
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, kind=kind, item_id=item_id)


def _text_column(model: type[TokenItem] | type[PhraseItem]) -> Any:
    # pyright cannot narrow `type[X] | type[Y]` on the negative (`else`) arm of
    # an `is` check, so the PhraseItem branch is cast explicitly.
    if model is TokenItem:
        return model.token_text
    return cast("type[PhraseItem]", model).display_text


def _branch_conditions(
    model: type[TokenItem] | type[PhraseItem],
    kind: str,
    *,
    user_id: uuid.UUID,
    language_code: str,
    target_language_code: str,
    statuses: list[str],
    confidence_min: int | None,
    confidence_max: int | None,
    tags: list[str],
    q: str | None,
    added_after: datetime | None,
    added_by: str,
) -> list[Any]:
    text_col = _text_column(model)
    conditions: list[Any] = [
        model.user_id == user_id,
        model.language_code == language_code,
        model.status.in_(statuses),
    ]
    if added_by == "user":
        conditions.append(model.added_by == "user")
    if confidence_min is not None or confidence_max is not None:
        conf: list[Any] = []
        if confidence_min is not None:
            conf.append(model.confidence >= confidence_min)
        if confidence_max is not None:
            conf.append(model.confidence <= confidence_max)
        # narrows only tracked rows; known/ignored pass (spec §3.1)
        conditions.append(or_(model.status != "tracked", and_(*conf)))
    for tag in tags:
        conditions.append(
            exists().where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == kind,
                ItemTag.item_id == model.id,
                ItemTag.tag_name == tag,
            )
        )
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                text_col.ilike(pattern),
                exists().where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == kind,
                    PersonalTranslation.item_id == model.id,
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                    PersonalTranslation.translation_text.ilike(pattern),
                ),
            )
        )
    if added_after is not None:
        conditions.append(model.created_at >= added_after)
    return conditions


def _branch_select(
    model: type[TokenItem] | type[PhraseItem], kind: str, conditions: list[Any]
) -> Select[Any]:
    text_col = _text_column(model)
    return select(
        model.id.label("id"),
        literal(kind).label("kind"),
        text_col.label("text"),
        model.status.label("status"),
        model.confidence.label("confidence"),
        model.created_at.label("created_at"),
    ).where(*conditions)


async def list_items(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    language_code: str,
    target_language_code: str,
    kind: str,
    statuses: list[str],
    confidence_min: int | None,
    confidence_max: int | None,
    tags: list[str],
    q: str | None,
    added_after: datetime | None,
    sort: str,
    sort_dir: str,
    page: int,
    page_size: int,
    added_by: str = "user",
) -> tuple[list[VocabListItem], int]:
    """Paginated vocabulary list (spec §3.1). `kind` selects `"token"` |
    `"phrase"` | `"all"` — token and phrase rows are combined via UNION ALL
    so both kinds can appear side by side in one page."""
    common: dict[str, Any] = {
        "user_id": user_id,
        "language_code": language_code,
        "target_language_code": target_language_code,
        "statuses": statuses,
        "confidence_min": confidence_min,
        "confidence_max": confidence_max,
        "tags": tags,
        "q": q,
        "added_after": added_after,
        "added_by": added_by,
    }
    branches: list[Select[Any]] = []
    if kind in ("token", "all"):
        branches.append(
            _branch_select(TokenItem, "token", _branch_conditions(TokenItem, "token", **common))
        )
    if kind in ("phrase", "all"):
        branches.append(
            _branch_select(
                PhraseItem, "phrase", _branch_conditions(PhraseItem, "phrase", **common)
            )
        )
    base = branches[0] if len(branches) == 1 else union_all(*branches)
    sub = base.subquery()

    total = (await session.execute(select(func.count()).select_from(sub))).scalar_one()

    order_col = sub.c.text if sort == "text" else sub.c.created_at
    order_by = order_col.asc() if sort_dir == "asc" else order_col.desc()
    rows = (
        await session.execute(
            select(sub)
            .order_by(order_by, sub.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    if not rows:
        return [], total

    ids_by_kind: dict[str, list[uuid.UUID]] = {}
    for r in rows:
        ids_by_kind.setdefault(r.kind, []).append(r.id)

    primary_map: dict[tuple[str, uuid.UUID], PersonalTranslation] = {}
    tags_map: dict[tuple[str, uuid.UUID], list[str]] = {}
    for row_kind, ids in ids_by_kind.items():
        for t in (
            await session.execute(
                select(PersonalTranslation).where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == row_kind,
                    PersonalTranslation.item_id.in_(ids),
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                )
            )
        ).scalars():
            primary_map[(row_kind, t.item_id)] = t
        for item_id, tag_name in (
            await session.execute(
                select(ItemTag.item_id, ItemTag.tag_name)
                .where(
                    ItemTag.owner_user_id == user_id,
                    ItemTag.item_kind == row_kind,
                    ItemTag.item_id.in_(ids),
                )
                .order_by(ItemTag.tag_name)
            )
        ).all():
            tags_map.setdefault((row_kind, item_id), []).append(tag_name)

    texts = [r.text for r in rows if r.kind == "token"]

    pos_map: dict[str, str] = {}
    if texts:
        pos_map = {
            headword: pos
            for headword, pos in (
                await session.execute(
                    select(DictionaryEntry.headword_normalized, DictionaryEntry.part_of_speech)
                    .distinct(DictionaryEntry.headword_normalized)
                    .join(
                        DictionarySourceVersion,
                        DictionaryEntry.source_version_id == DictionarySourceVersion.id,
                    )
                    .where(
                        DictionarySourceVersion.status == "active",
                        DictionaryEntry.source_language_code == language_code,
                        DictionaryEntry.headword_normalized.in_(texts),
                        DictionaryEntry.part_of_speech.is_not(None),
                    )
                    .order_by(DictionaryEntry.headword_normalized, DictionaryEntry.entry_key)
                )
            ).all()
            if pos is not None
        }

    context_map: dict[str, str] = {}
    if texts:
        # One example sentence per token: latest lesson's occurrence (spec §3.1).
        occ = (
            select(
                LessonTokenOccurrence.normalized_text.label("norm"),
                LessonSegment.text.label("segment_text"),
            )
            .distinct(LessonTokenOccurrence.normalized_text)
            .join(Lesson, LessonTokenOccurrence.lesson_id == Lesson.id)
            .join(LessonSegment, LessonTokenOccurrence.segment_id == LessonSegment.id)
            .where(
                Lesson.owner_user_id == user_id,
                Lesson.language_code == language_code,
                LessonTokenOccurrence.normalized_text.in_(texts),
            )
            .order_by(
                LessonTokenOccurrence.normalized_text,
                Lesson.created_at.desc(),
                LessonTokenOccurrence.ordinal_in_lesson,
            )
        )
        context_map = {  # noqa: C416 -- explicit unpack keeps Row types clear for pyright
            norm: segment_text for norm, segment_text in (await session.execute(occ)).all()
        }

    result: list[VocabListItem] = []
    for r in rows:
        primary = primary_map.get((r.kind, r.id))
        is_token = r.kind == "token"
        result.append(
            VocabListItem(
                item_id=r.id,
                kind=r.kind,
                text=r.text,
                status=r.status,
                confidence=r.confidence,
                primary_translation_text=primary.translation_text if primary else None,
                primary_translation_target=(primary.target_language_code if primary else None),
                tags=tags_map.get((r.kind, r.id), []),
                pos=pos_map.get(r.text) if is_token else None,
                context=context_map.get(r.text) if is_token else None,
                created_at=r.created_at,
            )
        )
    return result, total


async def remove_tag(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    tag_name: str,
) -> list[str]:
    _check_kind(kind)
    item = await _owned_item(session, user_id=user_id, kind=kind, item_id=item_id)
    _promote_to_user(item)
    await session.execute(
        delete(ItemTag).where(
            ItemTag.owner_user_id == user_id,
            ItemTag.item_kind == kind,
            ItemTag.item_id == item_id,
            ItemTag.tag_name == tag_name,
        )
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, kind=kind, item_id=item_id)


async def bulk_action(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    action: str,
    tag_name: str | None,
) -> int:
    """Bulk operation over the caller's token AND phrase items (spec §3.2).

    Unknown/foreign ids are silently skipped. One transaction.
    """
    owned_by_kind: dict[str, list[uuid.UUID]] = {}
    for kind, model in _MODEL_BY_KIND.items():
        ids = (
            (
                await session.execute(
                    select(model.id).where(model.user_id == user_id, model.id.in_(item_ids))
                )
            )
            .scalars()
            .all()
        )
        if ids:
            owned_by_kind[kind] = list(ids)
    if not owned_by_kind:
        return 0

    if action in ("set_known", "set_ignored"):
        new_status = "known" if action == "set_known" else "ignored"
        for kind, ids in owned_by_kind.items():
            model = _MODEL_BY_KIND[kind]
            await session.execute(
                update(model)
                .where(model.id.in_(ids))
                .values(status=new_status, confidence=None, added_by="user")
            )
    elif action == "delete":
        for kind, ids in owned_by_kind.items():
            for satellite in (PersonalTranslation, PersonalNote, ItemTag):
                await session.execute(
                    delete(satellite).where(
                        satellite.owner_user_id == user_id,
                        satellite.item_kind == kind,
                        satellite.item_id.in_(ids),
                    )
                )
            model = _MODEL_BY_KIND[kind]
            await session.execute(delete(model).where(model.id.in_(ids)))
    elif action == "add_tag":
        assert tag_name is not None  # validated at the API layer
        for kind, ids in owned_by_kind.items():
            model = _MODEL_BY_KIND[kind]
            await session.execute(update(model).where(model.id.in_(ids)).values(added_by="user"))
            for item_id in ids:
                await session.execute(
                    pg_insert(ItemTag)
                    .values(
                        id=uuid.uuid4(),
                        owner_user_id=user_id,
                        item_kind=kind,
                        item_id=item_id,
                        tag_name=tag_name,
                    )
                    .on_conflict_do_nothing(constraint="uq_item_tags")
                )
    await session.commit()
    return sum(len(ids) for ids in owned_by_kind.values())


async def list_phrases(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str
) -> list[PhraseItem]:
    return list(
        (
            await session.execute(
                select(PhraseItem)
                .where(
                    PhraseItem.user_id == user_id,
                    PhraseItem.language_code == language_code,
                )
                .order_by(PhraseItem.created_at, PhraseItem.id)
            )
        )
        .scalars()
        .all()
    )
