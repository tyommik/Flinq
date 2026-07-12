import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'

import { isWord, type Sentence } from '@/api/reader'
import { cn } from '@/lib/utils'

import { BottomToolbar } from './BottomToolbar'
import { paginate, pageIndexForOrdinal } from './pagination'
import { PageView } from './PageView'
import { buildPhraseIndex, buildSelection, type PhraseMatch } from './phraseMatching'
import { useReaderStore } from './readerStore'
import { ReaderTopBar } from './ReaderTopBar'
import { DEFAULT_TRANSLATION_LANG, SentenceView } from './SentenceView'
import { UndoToast } from './UndoToast'
import { usePhraseSelection } from './usePhraseSelection'
import { usePositionSync } from './usePositionSync'
import { useReaderHotkeys } from './useReaderHotkeys'
import {
  useBulkKnown,
  useLessonContent,
  useLessonDetail,
  usePhrases,
  useTokenStatuses,
  useUndoBulk,
} from './useReaderQueries'
import { useSwipe } from './useSwipe'
import { WordCard } from './WordCard'
import type { SelectedItem } from './selectedItem'

interface Props {
  lang: string
  lessonId: string
}

const FONT_SIZE_CLASS = ['text-base', 'text-lg', 'text-xl'] as const
const LINE_HEIGHT_CLASS = ['leading-normal', 'leading-relaxed', 'leading-loose'] as const

export function ReaderPage({ lang, lessonId }: Props) {
  const navigate = useNavigate()
  const { data: lessonDetail, isError: lessonDetailError } = useLessonDetail(lessonId)
  const status = lessonDetail?.status
  const contentEnabled = status === 'ready'

  const { data: content, isLoading: contentLoading } = useLessonContent(lessonId, contentEnabled)
  const { data: statuses } = useTokenStatuses(lessonId, contentEnabled)

  const [selectedWord, setSelectedWord] = useState<SelectedItem | null>(null)
  const [toastCount, setToastCount] = useState<number | null>(null)
  const [bulkErrorVisible, setBulkErrorVisible] = useState(false)

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
  const flatSentences = useMemo(
    () => (content ? content.paragraphs.flatMap((p) => p.sentences) : []),
    [content],
  )

  // Reader state (page/sentence position, the armed undo action, any visible
  // toast) is global zustand store state, not scoped to a lesson. Without an
  // explicit reset keyed on lessonId, navigating lesson A -> lesson B leaves
  // A's position and armed undo action stale and active against B's UI —
  // e.g. Ctrl+Z on lesson B could undo lesson A's bulk-known action. This
  // must run BEFORE the position-restore init effect below so the new
  // lesson never observes the previous lesson's leftover state.
  useEffect(() => {
    setPageIndex(0)
    setSentenceFlatIndex(0)
    setLastBulkActionId(null)
    setToastCount(null)
    setBulkErrorVisible(false)
    setSelectedWord(null)
  }, [lessonId, setPageIndex, setSentenceFlatIndex, setLastBulkActionId])

  // Tracks which lesson's position has already been restored, so re-renders
  // (or content/lessonDetail refetches) for the same lesson don't re-run
  // init, but a genuine lesson change does.
  const initializedRef = useRef<string | null>(null)
  useEffect(() => {
    if (initializedRef.current === lessonId || !content || !lessonDetail) return
    const readerPosition = lessonDetail.reader_position
    const initialMode = readerPosition?.view_mode ?? 'page'
    setMode(initialMode)
    if (initialMode === 'sentence' && readerPosition?.current_segment_id) {
      const segId = readerPosition.current_segment_id
      const idx = flatSentences.findIndex((s) => s.seg_id === segId)
      setSentenceFlatIndex(idx === -1 ? 0 : idx)
    } else {
      setPageIndex(pageIndexForOrdinal(pages, readerPosition?.current_token_ordinal ?? null))
    }
    initializedRef.current = lessonId
  }, [lessonId, content, lessonDetail, pages, flatSentences, setMode, setPageIndex, setSentenceFlatIndex])

  const statusMap = statuses ?? {}
  const currentPage = pages[pageIndex] ?? pages[0]
  const canPrev = pageIndex > 0
  const canNext = pageIndex < pages.length - 1

  const clampedSentenceIndex = Math.min(Math.max(sentenceFlatIndex, 0), Math.max(flatSentences.length - 1, 0))
  const currentSentence = flatSentences[clampedSentenceIndex]
  const canPrevSentence = clampedSentenceIndex > 0
  const canNextSentence = clampedSentenceIndex < flatSentences.length - 1

  const maxWordOrdinal = useMemo(() => {
    const lastPage = pages[pages.length - 1]
    return lastPage ? lastPage.toOrdinal : -1
  }, [pages])

  const currentOrdinalForProgress = useMemo(() => {
    if (mode === 'page') return currentPage?.toOrdinal ?? null
    const words = currentSentence?.tokens.filter(isWord) ?? []
    return words.length > 0 ? (words[words.length - 1]?.i ?? null) : null
  }, [mode, currentPage, currentSentence])

  const progressPercent = useMemo(() => {
    if (currentOrdinalForProgress == null || maxWordOrdinal < 0) return 0
    if (maxWordOrdinal === 0) return 100
    return Math.min(100, Math.max(0, Math.round((currentOrdinalForProgress / maxWordOrdinal) * 100)))
  }, [currentOrdinalForProgress, maxWordOrdinal])

  const readyForInteraction = contentEnabled && !!content

  const contentLang = content?.language_code ?? lang
  const phrases = usePhrases(contentLang, readyForInteraction)
  const phraseIndex = useMemo(() => buildPhraseIndex(phrases.data ?? []), [phrases.data])

  function handlePhraseSelect(range: { from: number; to: number }, sentence: Sentence) {
    const sel = buildSelection(sentence, range.from, range.to)
    if (!sel) return
    setSelectedWord({
      kind: 'phrase', t: sel.displayText, n: sel.text,
      i: sel.firstOrdinal, sentenceText: sentence.text,
    })
  }

  function handlePhraseClick(match: PhraseMatch, sentence: Sentence) {
    const slice = sentence.tokens.slice(match.startIdx, match.endIdx + 1)
    const display = slice
      .map((t) => ('t' in t ? t.t : 'p' in t ? t.p : t.ws))
      .join('')
      .trim()
    const first = slice.find(isWord)
    setSelectedWord({
      kind: 'phrase', t: display, n: match.entry.words.join(' '),
      i: first?.i ?? 0, sentenceText: sentence.text,
    })
  }

  const { dragRange, containerProps } = usePhraseSelection({
    enabled: readyForInteraction,
    sentences: flatSentences,
    onSelect: handlePhraseSelect,
  })

  const selectedSentenceText = useMemo(() => {
    if (!selectedWord) return null
    if (selectedWord.sentenceText) return selectedWord.sentenceText
    const sentence = flatSentences.find((s) =>
      s.tokens.some((tok) => isWord(tok) && tok.i === selectedWord.i),
    )
    return sentence?.text ?? null
  }, [selectedWord, flatSentences])

  const handleWordClick = (w: { t: string; n: string; i: number }) =>
    setSelectedWord({ kind: 'token', ...w, sentenceText: null })

  function handleEscape() {
    // usePhraseSelection has its own window Escape listener that cancels an
    // active drag; both fire on the same keypress, so without this bail-out
    // cancelling a drag would also navigate the user out of the reader.
    if (dragRange) return
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
      onError: () => {
        // The action may no longer be undoable (already undone, expired,
        // etc.) — disarm undo rather than leave a dead "Отменить" button.
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
        onError: () => {
          // Do not advance the page on failure — show a transient error
          // instead so the user knows the page wasn't marked known.
          setBulkErrorVisible(true)
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

  useEffect(() => {
    if (!bulkErrorVisible) return
    const timer = window.setTimeout(() => setBulkErrorVisible(false), 4000)
    return () => window.clearTimeout(timer)
  }, [bulkErrorVisible])

  if (lessonDetailError) {
    return (
      <div
        data-testid="reader-error"
        className="flex min-h-[50vh] flex-col items-center justify-center gap-4"
      >
        <p className="text-destructive">Не удалось загрузить урок</p>
        <Link to="/learn/$lang/library" params={{ lang }} className="text-primary underline">
          В библиотеку
        </Link>
      </div>
    )
  }

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

  const fontClass = cn(
    FONT_SIZE_CLASS[font.size],
    LINE_HEIGHT_CLASS[font.lineHeight],
    font.serif && 'font-serif',
  )

  return (
    <div className={cn('mx-auto max-w-screen-2xl px-6 pb-24', selectedWord && 'md:pr-[344px]')}>
      <ReaderTopBar
        lang={lang}
        progressPercent={progressPercent}
        mode={mode}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={toggleSidebar}
      />

      <div
        className={cn('py-6', fontClass)}
        onTouchStart={swipeHandlers.onTouchStart}
        onTouchEnd={swipeHandlers.onTouchEnd}
        {...containerProps}
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
              phraseIndex={phraseIndex}
              dragRange={dragRange}
              onWordClick={handleWordClick}
              onPhraseClick={handlePhraseClick}
            />
          </div>
        )}
        {!contentLoading && content && mode === 'sentence' && currentSentence && (
          <div data-testid="sentence-view-slot">
            <SentenceView
              lessonId={lessonId}
              sentence={currentSentence}
              statuses={statusMap}
              phraseIndex={phraseIndex}
              dragRange={dragRange}
              lang={content.language_code}
              targetLang={DEFAULT_TRANSLATION_LANG}
              onWordClick={handleWordClick}
              onPhraseClick={handlePhraseClick}
            />
          </div>
        )}
      </div>

      {!contentLoading && content && (
        <>
          <button
            type="button"
            aria-label={mode === 'sentence' ? 'Предыдущее предложение' : 'Предыдущая страница'}
            onClick={handlePrev}
            disabled={mode === 'sentence' ? !canPrevSentence : !canPrev}
            className="fixed left-2 top-1/2 z-10 -translate-y-1/2 rounded-md px-2 py-1 text-3xl text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-30"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label={mode === 'sentence' ? 'Следующее предложение' : 'Следующая страница'}
            onClick={handleNext}
            disabled={mode === 'sentence' ? !canNextSentence : !canNext}
            className={cn(
              'fixed right-2 top-1/2 z-10 -translate-y-1/2 rounded-md px-2 py-1 text-3xl text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-30',
              selectedWord && 'md:right-[336px]',
            )}
          >
            ›
          </button>
        </>
      )}

      <BottomToolbar
        mode={mode}
        onToggleMode={() => setMode(mode === 'page' ? 'sentence' : 'page')}
        panelOpen={selectedWord !== null}
      />

      <WordCard
        word={selectedWord}
        lang={content?.language_code ?? lang}
        target={DEFAULT_TRANSLATION_LANG}
        lessonId={lessonId}
        onClose={() => setSelectedWord(null)}
        sentenceText={selectedSentenceText}
      />

      {toastCount != null && (
        <UndoToast count={toastCount} onUndo={handleUndo} onDismiss={() => setToastCount(null)} />
      )}

      {bulkErrorVisible && (
        <div
          data-testid="bulk-error"
          className="fixed inset-x-0 bottom-6 z-[var(--z-toast)] flex justify-center"
        >
          <div className="rounded-full border border-destructive bg-card px-4 py-2 text-sm text-destructive shadow-lg">
            Не удалось сохранить
          </div>
        </div>
      )}
    </div>
  )
}
