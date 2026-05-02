import { useState } from 'react'
import { Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useLibraryStore } from './libraryStore'
import { ImportLessonDialog } from './ImportLessonDialog'

export function FilterRow() {
  const search = useLibraryStore((s) => s.search)
  const setSearch = useLibraryStore((s) => s.setSearch)
  const [importOpen, setImportOpen] = useState(false)

  return (
    <div className="flex items-center gap-4 py-5">
      <div className="relative w-[420px] max-w-full">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Поиск в Библиотеке"
          value={search}
          onChange={(e) => { setSearch(e.target.value) }}
          className="pl-10"
        />
      </div>
      <div className="ml-auto">
        <Button onClick={() => { setImportOpen(true) }}>+ Импортировать урок</Button>
      </div>
      <ImportLessonDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  )
}
