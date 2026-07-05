"""Assemble the LingQ-shaped tokenized lesson content (spec API-1).

User-independent: built purely from lesson facts. Whitespace tokens are the
raw_text gaps between consecutive occurrences inside a sentence, so
concatenating the stream reproduces the sentence text byte-for-byte.

Note: `flinq.modules.lesson_library.service.process_lesson_import` only ever
persists `LessonSegment` rows with `segment_type="sentence"` — no paragraph
segment rows exist. Paragraph boundaries are therefore recomputed here with
the same pure, deterministic `RegexSegmenter.split_paragraphs` the import
pipeline used, and sentences are grouped into paragraphs by char offset.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
from flinq.modules.lesson_library.tokenization import RegexSegmenter
from flinq.modules.reader_state.schemas import (
    LessonContentResponse,
    ParagraphOut,
    PunctToken,
    SentenceOut,
    Token,
    WhitespaceToken,
    WordToken,
)


async def build_lesson_content(session: AsyncSession, lesson: Lesson) -> LessonContentResponse:
    sentences = list(
        (
            await session.scalars(
                select(LessonSegment)
                .where(
                    LessonSegment.lesson_id == lesson.id,
                    LessonSegment.segment_type == "sentence",
                )
                .order_by(LessonSegment.ordinal)
            )
        ).all()
    )
    occurrences = list(
        (
            await session.scalars(
                select(LessonTokenOccurrence)
                .where(LessonTokenOccurrence.lesson_id == lesson.id)
                .order_by(LessonTokenOccurrence.ordinal_in_lesson)
            )
        ).all()
    )
    by_segment: dict[object, list[LessonTokenOccurrence]] = {}
    for occ in occurrences:
        by_segment.setdefault(occ.segment_id, []).append(occ)

    word_count = sum(1 for occ in occurrences if occ.is_word_like)
    paragraph_spans = RegexSegmenter(lesson.language_code).split_paragraphs(lesson.raw_text)

    def tokens_for(sentence: LessonSegment) -> list[Token]:
        out: list[Token] = []
        pos = sentence.start_char_offset
        for occ in by_segment.get(sentence.id, []):
            if occ.start_char_offset > pos:
                out.append(WhitespaceToken(ws=lesson.raw_text[pos : occ.start_char_offset]))
            if occ.is_word_like:
                out.append(
                    WordToken(t=occ.surface_text, n=occ.normalized_text, i=occ.ordinal_in_lesson)
                )
            else:
                out.append(PunctToken(p=occ.surface_text))
            pos = occ.end_char_offset
        if pos < sentence.end_char_offset:
            out.append(WhitespaceToken(ws=lesson.raw_text[pos : sentence.end_char_offset]))
        return out

    para_out: list[ParagraphOut] = []
    for para in paragraph_spans:
        inner = [
            SentenceOut(
                seg_id=s.id,
                index=s.ordinal,
                text=s.text,
                normalized_text=s.text.lower(),
                tokens=tokens_for(s),
            )
            for s in sentences
            if para.start <= s.start_char_offset and s.end_char_offset <= para.end
        ]
        para_out.append(ParagraphOut(sentences=inner))
    return LessonContentResponse(
        lesson_id=lesson.id,
        language_code=lesson.language_code,
        word_count=word_count,
        paragraphs=para_out,
    )
