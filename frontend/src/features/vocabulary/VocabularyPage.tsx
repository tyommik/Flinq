import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { VocabListItem } from '@/api/vocabulary'
import { WordCard } from '@/features/reader/WordCard'
import { BulkActionsMenu, type BulkAction } from './BulkActionsMenu'
import { FilterPopover } from './FilterPopover'
import { PaginationNumbers } from './PaginationNumbers'
import { SearchInput } from './SearchInput'
import { useBulkAction, usePatchItem, useVocabInvalidate, useVocabList, VOCAB_TARGET } from './useVocabularyQuery'
import { useVocabularyStore } from './vocabularyStore'
import { VocabularyCardList } from './VocabularyCardList'
import { VocabularyTable } from './VocabularyTable'

interface Props {
  lang: string
  tab: 'all' | 'words' | 'phrases' | 'due'
}

const LINK_TABS = [
  { id: 'all', label: 'Все' },
  { id: 'words', label: 'Слова' },
] as const

const PAGE_SIZES = [25, 50, 100] as const

type SortOption = 'created_at:desc' | 'created_at:asc' | 'text:asc' | 'text:desc'

const SORT_OPTIONS: { id: SortOption; label: string }[] = [
  { id: 'created_at:desc', label: 'Сначала новые' },
  { id: 'created_at:asc', label: 'Сначала старые' },
  { id: 'text:asc', label: 'А–Я' },
  { id: 'text:desc', label: 'Я–А' },
]

const DAY_MS = 86400 * 1000

/**
 * Truncated to a UTC day boundary so the result is stable across renders
 * within the same day. Without this, computing `Date.now() - N*DAY_MS`
 * inline in render produces a millisecond-precision value that differs on
 * every render, changing the useVocabList queryKey and causing an infinite
 * refetch loop whenever addedPreset is '7d'/'30d'.
 */
export function addedAfterFromPreset(preset: 'all' | '7d' | '30d'): string | undefined {
  if (preset === 'all') return undefined
  const n = preset === '7d' ? 7 : 30
  const d = new Date(Date.now() - n * DAY_MS)
  d.setUTCHours(0, 0, 0, 0)
  return d.toISOString()
}

export function VocabularyPage({ lang, tab }: Props) {
  const q = useVocabularyStore((s) => s.q)
  const statuses = useVocabularyStore((s) => s.statuses)
  const confidence = useVocabularyStore((s) => s.confidence)
  const tags = useVocabularyStore((s) => s.tags)
  const addedPreset = useVocabularyStore((s) => s.addedPreset)
  const sort = useVocabularyStore((s) => s.sort)
  const sortDir = useVocabularyStore((s) => s.sortDir)
  const page = useVocabularyStore((s) => s.page)
  const pageSize = useVocabularyStore((s) => s.pageSize)
  const selection = useVocabularyStore((s) => s.selection)
  const showAuto = useVocabularyStore((s) => s.showAuto)
  const toggleSelected = useVocabularyStore((s) => s.toggleSelected)
  const selectMany = useVocabularyStore((s) => s.selectMany)
  const clearSelection = useVocabularyStore((s) => s.clearSelection)
  const setPage = useVocabularyStore((s) => s.setPage)
  const setPageSize = useVocabularyStore((s) => s.setPageSize)
  const setSort = useVocabularyStore((s) => s.setSort)
  const resetFilters = useVocabularyStore((s) => s.resetFilters)
  const filtersAreDefault = useVocabularyStore((s) => s.filtersAreDefault())

  const addedAfter = useMemo(() => addedAfterFromPreset(addedPreset), [addedPreset])

  const { data, isLoading, isError, refetch } = useVocabList({
    lang,
    target: VOCAB_TARGET,
    status: statuses,
    confidence_min: confidence?.[0],
    confidence_max: confidence?.[1],
    tag: tags,
    q: q || undefined,
    added_after: addedAfter,
    sort,
    sort_dir: sortDir,
    page,
    page_size: pageSize,
    kind: tab === 'words' ? 'token' : 'all',
    added_by: showAuto ? 'all' : 'user',
  })
  const patchItem = usePatchItem()
  const bulk = useBulkAction()
  const invalidateVocabList = useVocabInvalidate()

  const [deletedToast, setDeletedToast] = useState<number | null>(null)
  const [bulkErrorVisible, setBulkErrorVisible] = useState(false)
  const [selectedItem, setSelectedItem] = useState<VocabListItem | null>(null)

  function handleCardClose() {
    setSelectedItem(null)
    invalidateVocabList()
  }

  useEffect(() => {
    if (deletedToast === null) return
    const timer = window.setTimeout(() => setDeletedToast(null), 4000)
    return () => window.clearTimeout(timer)
  }, [deletedToast])

  useEffect(() => {
    if (!bulkErrorVisible) return
    const timer = window.setTimeout(() => setBulkErrorVisible(false), 4000)
    return () => window.clearTimeout(timer)
  }, [bulkErrorVisible])

  function handleBulkAction(action: BulkAction, tagName?: string) {
    bulk.mutateAsync({ item_ids: selection, action, tag_name: tagName })
      .then((res) => {
        clearSelection()
        if (action === 'delete') setDeletedToast(res.affected)
      })
      .catch(() => { setBulkErrorVisible(true) })
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const showSkeleton = data === undefined && isLoading
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  useEffect(() => {
    if (data && page > totalPages) setPage(totalPages)
  }, [data, page, totalPages, setPage])

  return (
    <div className="bg-[var(--vocab-page-bg)] [font-family:'Inter',system-ui,sans-serif]">
      <div className="mx-auto max-w-screen-2xl px-6">
      <h1 className="py-6 text-2xl font-bold tracking-tight">Словарь</h1>
      <div className="flex flex-wrap items-center gap-3 pb-5">
        <div className="inline-flex rounded-lg bg-[var(--vocab-subtabs-track)] p-0.5">
          {LINK_TABS.map((t) => {
            const active = tab === t.id
            return (
              <Link
                key={t.id}
                to="/learn/$lang/vocabulary"
                params={{ lang }}
                search={{ tab: t.id }}
                className={[
                  'flex h-8 items-center rounded-md px-6 text-[13px]',
                  active
                    ? 'border border-[#C7CCD4] bg-white font-semibold text-[var(--vocab-term-fg)] shadow-sm'
                    : 'text-[var(--vocab-muted-fg)]',
                ].join(' ')}
              >
                {t.label}
              </Link>
            )
          })}
          <button
            type="button"
            disabled
            title="Появится позже"
            className="flex h-8 items-center rounded-md px-6 text-[13px] text-[var(--vocab-muted-fg)] cursor-not-allowed"
          >
            Фразы
          </button>
          <button
            type="button"
            disabled
            title="Появится позже"
            className="flex h-8 items-center rounded-md px-6 text-[13px] text-[var(--vocab-muted-fg)] cursor-not-allowed"
          >
            К повторению
          </button>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <SearchInput />
          <FilterPopover />
          <Select
            value={`${sort}:${sortDir}`}
            onValueChange={(v) => {
              const [nextSort, nextSortDir] = v.split(':') as ['created_at' | 'text', 'asc' | 'desc']
              setSort(nextSort, nextSortDir)
            }}
          >
            <SelectTrigger size="sm" aria-label="Сортировка">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <BulkActionsMenu count={selection.length} onAction={handleBulkAction} />
        </div>
      </div>
      <div className="py-6">
        {showSkeleton && (
          <div data-testid="vocab-skeleton" className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-12 w-full animate-pulse rounded-md bg-muted" />
            ))}
          </div>
        )}
        {!showSkeleton && isError && (
          <div
            data-testid="vocab-error"
            role="alert"
            className="mb-4 flex items-center justify-between rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            <span>Не удалось загрузить словарь</span>
            <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {!showSkeleton && !isError && total === 0 && filtersAreDefault && (
          <div data-testid="vocab-empty-default" className="flex flex-col items-center justify-center py-20 text-center">
            <h2 className="text-xl font-semibold">В словаре пока пусто</h2>
            <p className="mt-2 text-muted-foreground">
              Начните с импорта урока — нажимайте на слова в reader, и они появятся здесь
            </p>
            <Button asChild className="mt-6">
              <Link to="/learn/$lang/library" params={{ lang }}>
                Перейти в библиотеку
              </Link>
            </Button>
          </div>
        )}
        {!showSkeleton && !isError && total === 0 && !filtersAreDefault && (
          <div data-testid="vocab-empty-filtered" className="flex flex-col items-center justify-center py-20 text-center">
            <h2 className="text-xl font-semibold">Ничего не найдено по текущим фильтрам</h2>
            <Button type="button" variant="outline" className="mt-6" onClick={resetFilters}>
              Сбросить фильтры
            </Button>
          </div>
        )}
        {!showSkeleton && !isError && total > 0 && (
          <>
            <div className="flex flex-wrap items-center justify-end gap-4 pb-5">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Показать:</span>
                <Select
                  value={String(pageSize)}
                  onValueChange={(v) => { setPageSize(Number(v) as 25 | 50 | 100) }}
                >
                  <SelectTrigger size="sm" aria-label="Размер страницы">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PAGE_SIZES.map((size) => (
                      <SelectItem key={size} value={String(size)}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <span className="text-sm text-muted-foreground">Всего: {total}</span>
              <PaginationNumbers page={page} totalPages={totalPages} onPage={setPage} />
            </div>
            <VocabularyTable
              items={items}
              selection={selection}
              onToggleSelected={toggleSelected}
              onSelectPage={selectMany}
              onClearSelection={clearSelection}
              onPick={(itemId, status, confidence) =>
                patchItem.mutate({ itemId, status, confidence })}
              onOpenTerm={setSelectedItem}
            />
            <VocabularyCardList
              items={items}
              selection={selection}
              onToggleSelected={toggleSelected}
              onSelectPage={selectMany}
              onClearSelection={clearSelection}
              onPick={(itemId, status, confidence) =>
                patchItem.mutate({ itemId, status, confidence })}
              onOpenTerm={setSelectedItem}
            />
          </>
        )}
      </div>

      {selectedItem && (
        <WordCard
          word={{
            kind: selectedItem.kind, t: selectedItem.text, n: selectedItem.text, i: -1,
            sentenceText: selectedItem.context,
          }}
          lang={lang}
          target={VOCAB_TARGET}
          lessonId={null}
          sentenceText={null}
          onClose={handleCardClose}
        />
      )}

      {deletedToast !== null && (
        <div
          data-testid="bulk-deleted-toast"
          className="fixed inset-x-0 bottom-6 z-[var(--z-toast)] flex justify-center"
        >
          <div className="rounded-full border border-border bg-card px-4 py-2 text-sm shadow-lg">
            {`Удалено ${deletedToast}`}
          </div>
        </div>
      )}

      {bulkErrorVisible && (
        <div
          data-testid="bulk-action-error"
          className="fixed inset-x-0 bottom-6 z-[var(--z-toast)] flex justify-center"
        >
          <div className="rounded-full border border-destructive bg-card px-4 py-2 text-sm text-destructive shadow-lg">
            Не удалось выполнить действие
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
