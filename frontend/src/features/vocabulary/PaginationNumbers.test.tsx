import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PaginationNumbers } from './PaginationNumbers'

describe('PaginationNumbers', () => {
  it('renders a single current-page circle with both arrows disabled when totalPages=1', () => {
    render(<PaginationNumbers page={1} totalPages={1} onPage={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()

    const pageButtons = screen.getAllByRole('button', { name: /^Страница \d+$/ })
    expect(pageButtons).toHaveLength(1)
    expect(pageButtons[0]).toHaveAccessibleName('Страница 1')
    expect(pageButtons[0]!.className).toContain('rounded-full')
  })

  it('renders 1 … 3 4 5 … 7 when totalPages=7, page=4, with no button for 2 or 6', () => {
    render(<PaginationNumbers page={4} totalPages={7} onPage={vi.fn()} />)

    for (const p of [1, 3, 4, 5, 7]) {
      expect(screen.getByRole('button', { name: `Страница ${p}` })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: 'Страница 2' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Страница 6' })).not.toBeInTheDocument()

    expect(screen.getAllByText('…')).toHaveLength(2)
  })

  it('fires onPage(5) when clicking «Страница 5»', () => {
    const onPage = vi.fn()
    render(<PaginationNumbers page={4} totalPages={7} onPage={onPage} />)

    fireEvent.click(screen.getByRole('button', { name: 'Страница 5' }))

    expect(onPage).toHaveBeenCalledWith(5)
  })

  it('fires onPage(page-1) and onPage(page+1) via the arrows', () => {
    const onPage = vi.fn()
    render(<PaginationNumbers page={4} totalPages={7} onPage={onPage} />)

    fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница' }))
    expect(onPage).toHaveBeenCalledWith(3)

    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }))
    expect(onPage).toHaveBeenCalledWith(5)
  })

  it('renders no ellipsis when totalPages=2, page=1', () => {
    render(<PaginationNumbers page={1} totalPages={2} onPage={vi.fn()} />)

    expect(screen.queryByText('…')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Страница 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Страница 2' })).toBeInTheDocument()
  })
})
