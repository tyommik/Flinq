import { useNavigate, useParams } from '@tanstack/react-router'
import { ChevronDown } from 'lucide-react'

import { meApi } from '@/api/me'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useUserStore } from '@/stores/userStore'

const LANG_NAMES: Record<string, string> = {
  en: 'English',
  ru: 'Русский',
  pt: 'Português',
}
const LANG_FLAGS: Record<string, string> = {
  en: '🇬🇧',
  ru: '🇷🇺',
  pt: '🇵🇹',
}

export function LanguagePicker() {
  const navigate = useNavigate()
  const params = useParams({ strict: false }) as { lang?: string }
  const user = useUserStore((s) => s.user)
  const setCurrentLang = useUserStore((s) => s.setCurrentLang)

  if (!user) return null
  const currentLang = params.lang ?? user.last_learning_language_code ?? user.learning_languages[0]
  if (!currentLang) return null

  async function pick(lang: string) {
    if (lang === currentLang) return
    try {
      await meApi.setLastLanguage(lang)
    } catch {
      // ignore — picker still navigates; backend will reject if invalid
    }
    setCurrentLang(lang)
    await navigate({ to: '/learn/$lang/library', params: { lang } })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm hover:bg-accent">
        <span>{LANG_FLAGS[currentLang]}</span>
        <span className="font-medium">{LANG_NAMES[currentLang] ?? currentLang}</span>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {user.learning_languages.map((code) => (
          <DropdownMenuItem
            key={code}
            onClick={() => { void pick(code) }}
            className="gap-2"
          >
            <span>{LANG_FLAGS[code]}</span>
            <span>{LANG_NAMES[code] ?? code}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
