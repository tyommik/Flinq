import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'

import { cn } from '@/lib/utils'

import { BottomToolbar } from './BottomToolbar'
import { paginate, pageIndexForOrdinal } from './pagination'
import { PageView } from './PageView'
import { useReaderStore } from './readerStore'
import { ReaderTopBar } from './ReaderTopBar'
import { useLessonContent, useLessonDetail, useTokenStatuses } from './useReaderQueries'
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
  const { data: lessonDetail } = useLessonDetail(lessonId)
  const status = lessonDetail?.status
  const contentEnabled = status === 'ready'

  const { data: content, isLoading: contentLoading } = useLessonContent(lessonId, contentEnabled)
  const { data: statuses } = useTokenStatuses(lessonId, contentEnabled)

  const [selectedWord, setSelectedWord] = useState<SelectedWord | null>(null)

  const mode = useReaderStore((s) => s.mode)
  const pageIndex = useReaderStore((s) => s.pageIndex)
  const sentenceFlatIndex = useReaderStore((s) => s.sentenceFlatIndex)
  const sidebarOpen = useReaderStore((s) => s.sidebarOpen)
  const font = useReaderStore((s) => s.font)
  const setMode = useReaderStore((s) => s.setMode)
  const setPageIndex = useReaderStore((s) => s.setPageIndex)
  const toggleSidebar = useReaderStore((s) => s.toggleSidebar)

  const pages = useMemo(() => (content ? paginate(content.paragraphs) : []), [content])

  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current || !content || !lessonDetail) return
    const initialMode = lessonDetail.reader_position?.view_mode ?? 'page'
    setMode(initialMode)
    setPageIndex(pageIndexForOrdinal(pages, lessonDetail.reader_position?.current_token_ordinal ?? null))
    initializedRef.current = true
  }, [content, lessonDetail, pages, setMode, setPageIndex])

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

  const currentPage = pages[pageIndex] ?? pages[0]
  const canPrev = pageIndex > 0
  const canNext = pageIndex < pages.length - 1
  const statusMap = statuses ?? {}

  const flatSentences = content ? content.paragraphs.flatMap((p) => p.sentences) : []
  const currentSentence = flatSentences[sentenceFlatIndex] ?? flatSentences[0]
  const sentenceText = currentSentence?.text ?? ''

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

      <div className={cn('py-6', fontClass)}>
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
              onPrev={() => setPageIndex(Math.max(0, pageIndex - 1))}
              onNext={() => setPageIndex(Math.min(pages.length - 1, pageIndex + 1))}
              canPrev={canPrev}
              canNext={canNext}
            />
          </div>
        )}
        {!contentLoading && content && mode === 'sentence' && (
          <div data-testid="sentence-view-slot">{sentenceText}</div>
        )}
      </div>

      <BottomToolbar mode={mode} onToggleMode={() => setMode(mode === 'page' ? 'sentence' : 'page')} />

      <WordCardPlaceholder
        word={selectedWord}
        status={selectedWord ? statusMap[selectedWord.n] : undefined}
        onClose={() => setSelectedWord(null)}
      />
    </div>
  )
}
