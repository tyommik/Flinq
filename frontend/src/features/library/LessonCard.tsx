import type { LessonSummary } from '@/api/lessons'
import { LessonCover } from './LessonCover'

interface Props {
  lesson: LessonSummary
}

export function LessonCard({ lesson }: Props) {
  return (
    <a
      href={`/learn/${lesson.language_code}/lessons/${lesson.id}`}
      className="block w-[220px] overflow-hidden rounded-lg border border-border bg-card transition-shadow hover:shadow-md"
    >
      <LessonCover title={lesson.title} languageCode={lesson.language_code} />
      <div className="flex h-[110px] flex-col gap-2 p-3">
        <h3 className="line-clamp-2 text-sm font-medium leading-snug">
          {lesson.title}
        </h3>
        <div className="mt-auto space-y-1">
          <div className="h-1 w-full rounded-full bg-secondary">
            <div className="h-full rounded-full bg-primary" style={{ width: '0%' }} />
          </div>
          <p className="text-xs text-muted-foreground">
            0% · {lesson.word_count.toString()} слов
          </p>
        </div>
      </div>
    </a>
  )
}
