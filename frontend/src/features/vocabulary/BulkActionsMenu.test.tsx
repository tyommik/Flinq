import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { BulkActionsMenu } from './BulkActionsMenu'

async function openMenu(name = 'Ещё действия (2)') {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name }))
  return user
}

describe('BulkActionsMenu', () => {
  it('trigger is disabled when count is 0', () => {
    render(<BulkActionsMenu count={0} onAction={() => {}} />)
    expect(screen.getByRole('button', { name: 'Ещё действия (0)' })).toBeDisabled()
  })

  it('trigger is enabled when count > 0', () => {
    render(<BulkActionsMenu count={3} onAction={() => {}} />)
    expect(screen.getByRole('button', { name: 'Ещё действия (3)' })).not.toBeDisabled()
  })

  it('«Отметить known» fires onAction("set_known")', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={2} onAction={onAction} />)
    const user = await openMenu()

    await user.click(screen.getByText('Отметить known'))

    expect(onAction).toHaveBeenCalledWith('set_known')
  })

  it('«Отметить ignored» fires onAction("set_ignored")', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={2} onAction={onAction} />)
    const user = await openMenu()

    await user.click(screen.getByText('Отметить ignored'))

    expect(onAction).toHaveBeenCalledWith('set_ignored')
  })

  it('delete does not fire onAction before confirm, fires after «Удалить» click', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={5} onAction={onAction} />)
    const user = await openMenu('Ещё действия (5)')

    await user.click(screen.getByText('Удалить из словаря'))

    expect(onAction).not.toHaveBeenCalled()
    expect(screen.getByText('Удалить 5 слов?')).toBeInTheDocument()
    expect(screen.getByText('Переводы, заметки и теги будут удалены')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Удалить' }))

    expect(onAction).toHaveBeenCalledWith('delete')
  })

  it('delete confirm dialog «Отмена» does not fire onAction', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={5} onAction={onAction} />)
    const user = await openMenu('Ещё действия (5)')

    await user.click(screen.getByText('Удалить из словаря'))
    await user.click(screen.getByRole('button', { name: 'Отмена' }))

    expect(onAction).not.toHaveBeenCalled()
    expect(screen.queryByText('Удалить 5 слов?')).not.toBeInTheDocument()
  })

  it('«Добавить тег…» opens an inline input, typed tag is passed to onAction', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={2} onAction={onAction} />)
    const user = await openMenu()

    await user.click(screen.getByText('Добавить тег…'))

    const input = screen.getByLabelText('Название тега')
    await user.type(input, 'verbs')
    await user.click(screen.getByRole('button', { name: 'Добавить' }))

    expect(onAction).toHaveBeenCalledWith('add_tag', 'verbs')
  })

  it('«Добавить тег…» input submits on Enter', async () => {
    const onAction = vi.fn()
    render(<BulkActionsMenu count={2} onAction={onAction} />)
    const user = await openMenu()

    await user.click(screen.getByText('Добавить тег…'))

    const input = screen.getByLabelText('Название тега')
    await user.type(input, 'nouns{Enter}')

    expect(onAction).toHaveBeenCalledWith('add_tag', 'nouns')
  })
})
