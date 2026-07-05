import { createRoute, useParams } from '@tanstack/react-router'

import { ReaderPage } from '@/features/reader/ReaderPage'

import { learnLangRoute } from './learn.$lang'

export const learnLessonRoute = createRoute({
  getParentRoute: () => learnLangRoute,
  path: 'lessons/$lessonId',
  component: function LessonReaderView() {
    const params = useParams({ from: '/learn/$lang/lessons/$lessonId' })
    return <ReaderPage lang={params.lang} lessonId={params.lessonId} />
  },
})
