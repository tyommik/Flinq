import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { ImportLessonDialog } from './ImportLessonDialog'

export function LibraryEmptyState() {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <h2 className="text-xl font-semibold">У вас пока нет уроков</h2>
      <p className="mt-2 text-muted-foreground">
        Импортируйте свой первый текст
      </p>
      <Button className="mt-6" onClick={() => { setOpen(true) }}>
        + Импортировать урок
      </Button>
      <ImportLessonDialog open={open} onOpenChange={setOpen} />
    </div>
  )
}
