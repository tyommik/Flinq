import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { meApi } from '@/api/me'
import { useUserStore } from '@/stores/userStore'

interface Props {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: Props) {
  const navigate = useNavigate()
  const setUser = useUserStore((s) => s.setUser)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['me'],
    queryFn: meApi.get,
    retry: false,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (data) {
      setUser(data)
      if (data.needs_onboarding) {
        void navigate({ to: '/onboarding' })
      }
    }
  }, [data, setUser, navigate])

  useEffect(() => {
    if (isError) {
      const isUnauth = error instanceof ApiError && error.status === 401
      if (isUnauth) {
        void navigate({ to: '/login' })
      }
    }
  }, [isError, error, navigate])

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }
  if (!data || data.needs_onboarding) return null
  return <>{children}</>
}
