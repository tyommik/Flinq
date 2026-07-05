import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'

import { isWord } from '@/api/reader'
import { cn } from '@/lib/utils'

import { BottomToolbar } from './BottomToolbar'
import { paginate, pageIndexForOrdinal } from './pagination'
import { PageView } from './PageView'
import { useReaderStore } from './readerStore'
import { ReaderTopBar } from './ReaderTopBar'
import { DEFAULT_TRANSLATION_LANG, SentenceView } from './SentenceView'
import { UndoToast } from './UndoToast'
import { usePositionSync } from './usePositionSync'
import { useReaderHotkeys } from './useReaderHotkeys'
import {
  useBulkKnown,
  useLessonContent,
  useLessonDetail,
  useTokenStatuses,
  useUndoBulk,
} from './useReaderQueries'
import { useSwipe } from './useSwipe'
import { WordCardPlaceholder } from './WordCardPlaceholder'

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  lang: string
  lessonId: string
}

const FONT_SIZE_CLASS = ['text-base', 'text-lg', 'text-xl'] as const
const LINE_HEIGHT_CLASS = ['leading-normal', 'leading-relaxed', 'leading-loose'] as const

export function ReaderPage({ lang, lessonId }: Props) {
  const navigate = useNavigate()
  const { data: lessonDetail } = useLessonDetail(lessonId)
  const status = lessonDetail?.status
  const contentEnabled = status === 'ready'

  const { data: content, isLoading: contentLoading } = useLessonContent(lessonId, contentEnabled)
  const { data: statuses } = useTokenStatuses(lessonId, contentEnabled)

  const [selectedWord, setSelectedWord] = useState<SelectedWord | null>(null)
  const [toastCount, setToastCount] = useState<number | null>(null)

  const mode = useReaderStore((s) => s.mode)
  const pageIndex = useReaderStore((s) => s.pageIndex)
  const sentenceFlatIndex = useReaderStore((s) => s.sentenceFlatIndex)
  const sidebarOpen = useReaderStore((s) => s.sidebarOpen)
  const font = useReaderStore((s) => s.font)
  const lastBulkActionId = useReaderStore((s) => s.lastBulkActionId)
  const setMode = useReaderStore((s) => s.setMode)
  const setPageIndex = useReaderStore((s) => s.setPageIndex)
  const setSentenceFlatIndex = useReaderStore((s) => s.setSentenceFlatIndex)
  const toggleSidebar = useReaderStore((s) => s.toggleSidebar)
  const setLastBulkActionId = useReaderStore((s) => s.setLastBulkActionId)

  const bulkKnown = useBulkKnown(lessonId)
  const undoBulk = useUndoBulk(lessonId)

  const pages = useMemo(() => (content ? paginate(content.paragraphs) : []), [content])

  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current || !content || !lessonDetail) return
    const initialMode = lessonDetail.reader_position?.view_mode ?? 'page'
    setMode(initialMode)
    setPageIndex(pageIndexForOrdinal(pages, lessonDetail.reader_position?.current_token_ordinal ?? null))
    initializedRef.current = true
  }, [content, lessonDetail, pages, setMode, setPageIndex])

  const statusMap = statuses ?? {}
  const currentPage = pages[pageIndex] ?? pages[0]
  const canPrev = pageIndex > 0
  const canNext = pageIndex < pages.length - 1

  const flatSentences = content ? content.paragraphs.flatMap((p) => p.sentences) : []
  const clampedSentenceIndex = Math.min(Math.max(sentenceFlatIndex, 0), Math.max(flatSentences.length - 1, 0))
  const currentSentence = flatSentences[clampedSentenceIndex]
  const canPrevSentence = clampedSentenceIndex > 0
  const canNextSentence = clampedSentenceIndex < flatSentences.length - 1

  const readyForInteraction = contentEnabled && !!content

  function handleEscape() {
    if (selectedWord) {
      setSelectedWord(null)
      return
    }
    void navigate({ to: '/learn/$lang/library', params: { lang } })
  }

  function handleUndo() {
    if (!lastBulkActionId) return
    undoBulk.mutate(lastBulkActionId, {
      onSuccess: () => {
        setLastBulkActionId(null)
        setToastCount(null)
      },
    })
  }

  function handlePrevPage() {
    if (!canPrev) return
    setPageIndex(Math.max(0, pageIndex - 1))
  }

  function handleNextPage() {
    if (!canNext || !currentPage) return

    if (currentPage.wordCount === 0) {
      // Empty-page marker from pagination (ordinals are 0/-1) — nothing to
      // mark known, just advance.
      setPageIndex(Math.min(pages.length - 1, pageIndex + 1))
      return
    }

    bulkKnown.mutate(
      {
        lesson_id: lessonId,
        from_ordinal: currentPage.fromOrdinal,
        to_ordinal: currentPage.toOrdinal,
      },
      {
        onSuccess: (result) => {
          setPageIndex(Math.min(pages.length - 1, pageIndex + 1))
          // Arm undo even when created_count === 0 (e.g. all words already
          // known) — the server-side bulk action still exists, so Ctrl+Z
          // must stay honest and be able to undo it.
          setLastBulkActionId(result.action_id)
          setToastCount(result.created_count > 0 ? result.created_count : null)
        },
      },
    )
  }

  function handlePrevSentence() {
    if (!canPrevSentence) return
    setSentenceFlatIndex(Math.max(0, clampedSentenceIndex - 1))
  }

  function handleNextSentence() {
    if (!canNextSentence) return
    setSentenceFlatIndex(Math.min(flatSentences.length - 1, clampedSentenceIndex + 1))
  }

  const handlePrev = mode === 'page' ? handlePrevPage : handlePrevSentence
  const handleNext = mode === 'page' ? handleNextPage : handleNextSentence

  useReaderHotkeys({
    enabled: readyForInteraction,
    onPrev: handlePrev,
    onNext: handleNext,
    onToggleMode: () => setMode(mode === 'page' ? 'sentence' : 'page'),
    onEscape: handleEscape,
    onUndo: lastBulkActionId ? handleUndo : undefined,
    onToggleSidebar: mode === 'page' ? toggleSidebar : undefined,
  })

  const positionSegmentId =
    mode === 'page' ? (currentPage?.sentences[0]?.sentence.seg_id ?? null) : (currentSentence?.seg_id ?? null)
  const positionOrdinal =
    mode === 'page' ? (currentPage?.fromOrdinal ?? null) : (currentSentence?.tokens.find(isWord)?.i ?? null)

  usePositionSync({
    lessonId,
    mode,
    currentSegmentId: positionSegmentId,
    currentOrdinal: positionOrdinal,
    enabled: readyForInteraction,
  })

  const swipeHandlers = useSwipe({ onSwipeLeft: handleNext, onSwipeRight: handlePrev })

  if (!lessonDetail) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <p className="text-muted-foreground">Загрузка…</p>
      </div>
    )
  }

  if (status === 'processing') {
    return (
      <div
        data-testid="reader-processing"
        className="flex min-h-[50vh] flex-col items-center justify-center gap-4"
      >
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-muted-foreground">Урок готовится…</p>
      </div>
    )
  }

  if (status === 'failed') {
    return (
      <div
        data-testid="reader-failed"
        className="flex min-h-[50vh] flex-col items-center justify-center gap-4"
      >
        <p className="text-destructive">Не удалось обработать урок</p>
        <Link to="/learn/$lang/library" params={{ lang }} className="text-primary underline">
          В библиотеку
        </Link>
      </div>
    )
  }

  if (status !== 'ready') {
    return (
      <div
        data-testid="reader-unavailable"
        className="flex min-h-[50vh] flex-col items-center justify-center gap-4"
      >
        <p className="text-muted-foreground">Урок недоступен</p>
        <Link to="/learn/$lang/library" params={{ lang }} className="text-primary underline">
          В библиотеку
        </Link>
      </div>
    )
  }

  const progressPercent =
    lessonDetail.word_count > 0
      ? Math.min(
          100,
          Math.round(
            ((lessonDetail.reader_position?.current_token_ordinal ?? 0) / lessonDetail.word_count) * 100,
          ),
        )
      : 0

  const fontClass = cn(
    FONT_SIZE_CLASS[font.size],
    LINE_HEIGHT_CLASS[font.lineHeight],
    font.serif && 'font-serif',
  )

  return (
    <div className="mx-auto max-w-screen-2xl px-6">
      <ReaderTopBar
        lang={lang}
        title={lessonDetail.title}
        progressPercent={progressPercent}
        mode={mode}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={toggleSidebar}
      />

      <div
        className={cn('py-6', fontClass)}
        onTouchStart={swipeHandlers.onTouchStart}
        onTouchEnd={swipeHandlers.onTouchEnd}
      >
        {contentLoading && (
          <div
            data-testid="reader-skeleton"
            className="h-64 w-full animate-pulse rounded-md bg-muted"
          />
        )}
        {!contentLoading && content && mode === 'page' && currentPage && (
          <div data-testid="page-view-slot">
            <PageView
              page={currentPage}
              statuses={statusMap}
              onWordClick={setSelectedWord}
              onPrev={handlePrevPage}
              onNext={handleNextPage}
              canPrev={canPrev}
              canNext={canNext}
            />
          </div>
        )}
        {!contentLoading && content && mode === 'sentence' && currentSentence && (
          <div data-testid="sentence-view-slot">
            <SentenceView
              lessonId={lessonId}
              sentence={currentSentence}
              statuses={statusMap}
              targetLang={DEFAULT_TRANSLATION_LANG}
              onWordClick={setSelectedWord}
              onPrev={handlePrevSentence}
              onNext={handleNextSentence}
              canPrev={canPrevSentence}
              canNext={canNextSentence}
            />
          </div>
        )}
      </div>

      <BottomToolbar mode={mode} onToggleMode={() => setMode(mode === 'page' ? 'sentence' : 'page')} />

      <WordCardPlaceholder
        word={selectedWord}
        status={selectedWord ? statusMap[selectedWord.n] : undefined}
        onClose={() => setSelectedWord(null)}
      />

      {toastCount != null && (
        <UndoToast count={toastCount} onUndo={handleUndo} onDismiss={() => setToastCount(null)} />
      )}
    </div>
  )
}
