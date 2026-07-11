import { createRoute, useParams, useSearch } from '@tanstack/react-router'

import { VocabularyPage } from '@/features/vocabulary/VocabularyPage'

import { learnLangRoute } from './learn.$lang'

const TABS = ['all', 'words', 'phrases', 'due'] as const
export type VocabTab = (typeof TABS)[number]

export const learnVocabularyRoute = createRoute({
  getParentRoute: () => learnLangRoute,
  path: 'vocabulary',
  validateSearch: (search: Record<string, unknown>): { tab: VocabTab } => ({
    tab: TABS.includes(search.tab as VocabTab) ? (search.tab as VocabTab) : 'all',
  }),
  component: function VocabularyView() {
    const params = useParams({ from: '/learn/$lang/vocabulary' })
    const { tab } = useSearch({ from: '/learn/$lang/vocabulary' })
    return <VocabularyPage lang={params.lang} tab={tab} />
  },
})
