import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'

import { authApi } from '@/api/auth'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useUserStore } from '@/stores/userStore'

export function AvatarMenu() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useUserStore((s) => s.user)
  const reset = useUserStore((s) => s.reset)

  if (!user) return null
  const initials = user.display_name
    .split(/\s+/)
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // ignore — clear local state regardless
    }
    reset()
    queryClient.clear()
    await navigate({ to: '/login', replace: true })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold">
        {initials}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem disabled>{user.display_name}</DropdownMenuItem>
        <DropdownMenuItem disabled className="text-xs text-muted-foreground">
          {user.email}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => { void logout() }}>Выйти</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
