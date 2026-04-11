import { useQuery } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'
import { fetchHealth } from '@/api/client'

export function IndexRoute() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
  })

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <header className="flex items-center gap-3">
        <BookOpen className="h-8 w-8" aria-hidden="true" />
        <h1 className="text-4xl font-bold tracking-tight">Flinq</h1>
      </header>
      <p className="mt-3 text-gray-600 dark:text-gray-400">
        Self-hosted content-driven language learning platform.
      </p>

      <section className="mt-10 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Backend health
        </h2>
        <div className="mt-2 font-mono text-sm">
          {isLoading && <span className="text-gray-500">Checking…</span>}
          {isError && (
            <span className="text-red-600 dark:text-red-400">
              Error: {error instanceof Error ? error.message : 'unknown'}
            </span>
          )}
          {data && (
            <span>
              status=
              <span className="text-green-600 dark:text-green-400">{data.status}</span>
              {' '}version={data.version}
            </span>
          )}
        </div>
      </section>

      <p className="mt-10 text-xs text-gray-500">
        This is a walking skeleton. See <code>docs/</code> for product and architecture decisions.
      </p>
    </main>
  )
}