import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'

import { authApi } from '@/api/auth'
import { ApiError } from '@/api/client'
import { meApi } from '@/api/me'
import { useUserStore } from '@/stores/userStore'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function LoginForm() {
  const navigate = useNavigate()
  const setUser = useUserStore((s) => s.setUser)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await authApi.login({ email, password, remember_me: remember })
      const me = await meApi.get()
      setUser(me)
      if (me.needs_onboarding) {
        await navigate({ to: '/onboarding' })
        return
      }
      const lang = me.last_learning_language_code ?? me.learning_languages[0]
      if (lang) {
        await navigate({ to: '/learn/$lang/library', params: { lang } })
      } else {
        await navigate({ to: '/onboarding' })
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Слишком много попыток. Попробуйте позже.')
      } else {
        setError('Неверный email или пароль')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4">
      <h1 className="text-3xl font-semibold text-center">Вход</h1>
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
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => { setPassword(e.target.value) }}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={remember}
          onCheckedChange={(v) => { setRemember(v === true) }}
        />
        Запомнить меня
      </label>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" className="w-full" disabled={submitting}>
        Вход
      </Button>
      <p className="text-sm text-center text-muted-foreground">
        Нет аккаунта?{' '}
        <Link to="/register" className="text-primary hover:underline">
          Зарегистрироваться
        </Link>
      </p>
    </form>
  )
}
