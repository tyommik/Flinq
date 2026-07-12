import type { ReactNode } from 'react'

interface Props {
  onClick: () => void
  children: ReactNode
}

/**
 * Подложка сохранённой (tracked) фразы. Hover расширяет зону попадания и
 * подложку геометрически (padding + равный отрицательный margin), не сдвигая
 * текст: клик по кромке — карточка фразы, клики по словам внутри гасятся в
 * TokenSpan (stopPropagation).
 */
export function PhraseSpan({ onClick, children }: Props) {
  return (
    <span
      data-testid="phrase-span"
      role="button"
      tabIndex={-1}
      onClick={onClick}
      className="cursor-pointer rounded bg-[var(--reader-tracked-bg)] px-1 -mx-1 py-0.5 -my-0.5 transition-all duration-100 hover:px-2 hover:-mx-2 hover:py-1.5 hover:-my-1.5"
    >
      {children}
    </span>
  )
}
