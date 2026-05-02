import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'

import { authApi } from '@/api/auth'
import { ApiError } from '@/api/client'
import { meApi } from '@/api/me'
import { useUserStore } from '@/stores/userStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function RegisterForm() {
  const navigate = useNavigate()
  const setUser = useUserStore((s) => s.setUser)
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await authApi.register({ display_name: displayName, email, password })
      const me = await meApi.get()
      setUser(me)
      await navigate({ to: '/onboarding' })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) setError('Этот email уже используется')
        else if (err.status === 403) setError('Регистрация закрыта администратором')
        else if (err.status === 422) setError('Минимум 10 символов в пароле')
        else if (err.status === 429) setError('Слишком много попыток. Попробуйте позже.')
        else setError('Не удалось зарегистрироваться')
      } else {
        setError('Не удалось зарегистрироваться')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4">
      <h1 className="text-3xl font-semibold text-center">Регистрация</h1>
      <div className="space-y-2">
        <Label htmlFor="name">Имя</Label>
        <Input
          id="name"
          autoComplete="name"
          required
          maxLength={80}
          value={displayName}
          onChange={(e) => { setDisplayName(e.target.value) }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="email">Электронная почта</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => { setEmail(e.target.value) }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Пароль</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          value={password}
          onChange={(e) => { setPassword(e.target.value) }}
        />
        <p className="text-xs text-muted-foreground">мин 10 символов</p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" className="w-full" disabled={submitting}>
        Создать аккаунт
      </Button>
      <p className="text-sm text-center text-muted-foreground">
        Уже есть аккаунт?{' '}
        <Link to="/login" className="text-primary hover:underline">
          Войти
        </Link>
      </p>
    </form>
  )
}
