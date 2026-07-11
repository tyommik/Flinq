import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { useVocabularyStore } from './vocabularyStore'

const DEBOUNCE_MS = 300

/** Toolbar search input: local state, debounced 300ms into store.setQ. */
export function SearchInput() {
  const storeQ = useVocabularyStore((s) => s.q)
  const setQ = useVocabularyStore((s) => s.setQ)
  const [value, setValue] = useState(storeQ)
  const lastSeenStoreQ = useRef(storeQ)

  useEffect(() => {
    // Sync local value when the store's q changes from outside this
    // component (e.g. resetFilters). Comparing against lastSeenStoreQ
    // (rather than just storeQ !== value) distinguishes "the store changed
    // because our own debounce just committed `value`" (storeQ becomes
    // equal to value → no-op) from "the store changed externally" (storeQ
    // now differs from what we last saw AND from our local value → sync).
    if (storeQ !== lastSeenStoreQ.current && storeQ !== value) {
      setValue(storeQ)
    }
    lastSeenStoreQ.current = storeQ
  }, [storeQ, value])

  useEffect(() => {
    // Skip scheduling when the local value already matches the store: avoids
    // firing setQ on mount (or after a store-driven sync) and spuriously
    // resetting page/selection when nothing actually changed.
    if (value === storeQ) return
    const handle = setTimeout(() => {
      setQ(value)
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [value, storeQ, setQ])

  return (
    <div className="relative w-[320px] max-w-full">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        placeholder="Поиск в словаре"
        value={value}
        onChange={(e) => { setValue(e.target.value) }}
        className="pl-10"
      />
    </div>
  )
}
