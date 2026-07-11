import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useVocabularyStore } from './vocabularyStore'

type Status = 'tracked' | 'known' | 'ignored'

const STATUS_OPTIONS: { id: Status; label: string }[] = [
  { id: 'tracked', label: 'Отслеживаемые' },
  { id: 'known', label: 'Изученные' },
  { id: 'ignored', label: 'Игнорируемые' },
]

const CONFIDENCE_LEVELS = [1, 2, 3, 4] as const

const ADDED_PRESETS: { id: 'all' | '7d' | '30d'; label: string }[] = [
  { id: '7d', label: '7 дней' },
  { id: '30d', label: '30 дней' },
  { id: 'all', label: 'Всё время' },
]

/** Toolbar filter popover: status / confidence / tags / date preset, no radix dependency. */
export function FilterPopover() {
  const [open, setOpen] = useState(false)
  const [tagDraft, setTagDraft] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  const statuses = useVocabularyStore((s) => s.statuses)
  const setStatuses = useVocabularyStore((s) => s.setStatuses)
  const confidence = useVocabularyStore((s) => s.confidence)
  const setConfidence = useVocabularyStore((s) => s.setConfidence)
  const tags = useVocabularyStore((s) => s.tags)
  const setTags = useVocabularyStore((s) => s.setTags)
  const addedPreset = useVocabularyStore((s) => s.addedPreset)
  const setAddedPreset = useVocabularyStore((s) => s.setAddedPreset)
  const showAuto = useVocabularyStore((s) => s.showAuto)
  const setShowAuto = useVocabularyStore((s) => s.setShowAuto)
  const resetFilters = useVocabularyStore((s) => s.resetFilters)

  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  const confidenceDisabled = !statuses.includes('tracked')
  const min = confidence?.[0] ?? 1
  const max = confidence?.[1] ?? 4

  function toggleStatus(id: Status) {
    const next = statuses.includes(id)
      ? statuses.filter((s) => s !== id)
      : [...statuses, id]
    setStatuses(next)
  }

  function addTag() {
    const t = tagDraft.trim()
    if (t === '') return
    if (!tags.includes(t)) setTags([...tags, t])
    setTagDraft('')
  }

  function removeTag(t: string) {
    setTags(tags.filter((x) => x !== t))
  }

  return (
    <div className="relative" ref={containerRef}>
      <Button
        type="button"
        variant="ghost"
        aria-expanded={open}
        onClick={() => { setOpen((v) => !v) }}
        className="h-8 border-0 px-2 text-[13px] font-normal text-[var(--vocab-muted-fg)] hover:bg-transparent hover:text-[var(--vocab-term-fg)] aria-expanded:bg-transparent aria-expanded:text-[var(--vocab-term-fg)]"
      >
        {'⊟ Фильтры'}
      </Button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-2 w-80 rounded-lg border border-border bg-popover p-4 text-sm text-popover-foreground shadow-md">
          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">Статус</legend>
            {STATUS_OPTIONS.map((opt) => (
              <label key={opt.id} className="flex items-center gap-2">
                <Checkbox
                  checked={statuses.includes(opt.id)}
                  onCheckedChange={() => { toggleStatus(opt.id) }}
                />
                {opt.label}
              </label>
            ))}
          </fieldset>

          <div className="mt-3 space-y-1.5">
            <span className="block text-xs font-medium text-muted-foreground">
              Уровень уверенности
            </span>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5">
                от
                <Select
                  disabled={confidenceDisabled}
                  value={String(min)}
                  onValueChange={(v) => { setConfidence([Number(v), max]) }}
                >
                  <SelectTrigger size="sm" aria-label="Уверенность от">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CONFIDENCE_LEVELS.map((lvl) => (
                      <SelectItem key={lvl} value={String(lvl)}>{lvl}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="flex items-center gap-1.5">
                до
                <Select
                  disabled={confidenceDisabled}
                  value={String(max)}
                  onValueChange={(v) => { setConfidence([min, Number(v)]) }}
                >
                  <SelectTrigger size="sm" aria-label="Уверенность до">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CONFIDENCE_LEVELS.map((lvl) => (
                      <SelectItem key={lvl} value={String(lvl)}>{lvl}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            </div>
          </div>

          <div className="mt-3 space-y-1.5">
            <span className="block text-xs font-medium text-muted-foreground">Теги</span>
            <Input
              placeholder="Добавить тег…"
              value={tagDraft}
              onChange={(e) => { setTagDraft(e.target.value) }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addTag()
                }
              }}
            />
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {tags.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { removeTag(t) }}
                    aria-label={`Удалить тег ${t}`}
                    className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs"
                  >
                    {t}
                    <span aria-hidden="true">✕</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <fieldset className="mt-3 space-y-1.5">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">Добавлено</legend>
            {ADDED_PRESETS.map((p) => (
              <label key={p.id} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="vocab-added-preset"
                  checked={addedPreset === p.id}
                  onChange={() => { setAddedPreset(p.id) }}
                />
                {p.label}
              </label>
            ))}
          </fieldset>

          <div className="mt-3">
            <label className="flex items-start gap-2">
              <Checkbox
                checked={showAuto}
                onCheckedChange={() => { setShowAuto(!showAuto) }}
              />
              <span className="leading-tight">
                <span className="block">Показывать авто-изученные</span>
                <span className="block text-xs text-muted-foreground">
                  слова, отмеченные изученными при листании
                </span>
              </span>
            </label>
          </div>

          <div className="mt-4 flex justify-end">
            <Button type="button" variant="outline" size="sm" onClick={resetFilters}>
              Сбросить
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
