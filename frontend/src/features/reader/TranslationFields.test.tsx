import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { TranslationOut } from '@/api/vocabulary'
import { TranslationFields } from './TranslationFields'

const tr = (id: string, text: string, primary = false): TranslationOut => ({
  id, text, target_language_code: 'ru', is_primary: primary, source_type: 'user',
})

function setup(translations: TranslationOut[]) {
  const onCreate = vi.fn().mockResolvedValue(undefined)
  const onUpdate = vi.fn().mockResolvedValue(undefined)
  const onDelete = vi.fn().mockResolvedValue(undefined)
  render(
    <TranslationFields
      translations={translations}
      onCreate={onCreate}
      onUpdate={onUpdate}
      onDelete={onDelete}
    />,
  )
  return { onCreate, onUpdate, onDelete }
}

describe('TranslationFields', () => {
  it('shows a single empty field when there are no variants and creates on Enter', async () => {
    const { onCreate } = setup([])
    const input = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith('каждый'))
  })

  it('renders one field per variant and updates an edited field on Enter', async () => {
    const { onUpdate } = setup([tr('T1', 'первый', true), tr('T2', 'второй')])
    const fields = screen.getAllByRole('textbox')
    expect(fields).toHaveLength(2)
    fireEvent.change(fields[1]!, { target: { value: 'второй!' } })
    fireEvent.keyDown(fields[1]!, { key: 'Enter' })
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith('T2', 'второй!'))
  })

  it('does not call anything when the value is unchanged on blur', async () => {
    const { onCreate, onUpdate, onDelete } = setup([tr('T1', 'первый', true)])
    fireEvent.blur(screen.getByDisplayValue('первый'))
    await new Promise((r) => setTimeout(r, 20))
    expect(onCreate).not.toHaveBeenCalled()
    expect(onUpdate).not.toHaveBeenCalled()
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('deletes when a field is emptied and on ✕ click', async () => {
    const { onDelete } = setup([tr('T1', 'первый', true), tr('T2', 'второй')])
    const first = screen.getByDisplayValue('первый')
    fireEvent.change(first, { target: { value: '  ' } })
    fireEvent.keyDown(first, { key: 'Enter' })
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('T1'))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить вариант: второй' }))
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('T2'))
  })

  it('adds a pending empty field via + and creates from it', async () => {
    const { onCreate } = setup([tr('T1', 'первый', true)])
    fireEvent.click(screen.getByRole('button', { name: 'Добавить вариант' }))
    const empty = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(empty, { target: { value: 'новый' } })
    fireEvent.keyDown(empty, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith('новый'))
  })

  it('keeps the draft and shows an inline error when saving fails, then retries', async () => {
    const onCreate = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce(undefined)
    render(
      <TranslationFields translations={[]} onCreate={onCreate}
        onUpdate={vi.fn()} onDelete={vi.fn()} />,
    )
    const input = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText('Не удалось сохранить')
    expect((input as HTMLInputElement).value).toBe('каждый')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.queryByText('Не удалось сохранить')).not.toBeInTheDocument(),
    )
  })

  it('shows the duplicate-variant message when onUpdate rejects with a 409 ApiError', async () => {
    const onUpdate = vi.fn().mockRejectedValueOnce(new ApiError(409, 'duplicate translation text'))
    render(
      <TranslationFields translations={[tr('T1', 'первый', true), tr('T2', 'второй')]}
        onCreate={vi.fn()} onUpdate={onUpdate} onDelete={vi.fn()} />,
    )
    const second = screen.getByDisplayValue('второй')
    fireEvent.change(second, { target: { value: 'первый' } })
    fireEvent.keyDown(second, { key: 'Enter' })
    await screen.findByText('Такой вариант уже есть')
    expect((second as HTMLInputElement).value).toBe('первый')
    expect(screen.queryByText('Не удалось сохранить')).not.toBeInTheDocument()
  })

  it('does not double-fire onCreate when Enter is followed by blur before the commit resolves', async () => {
    let resolve!: () => void
    const onCreate = vi.fn(() => new Promise<void>((r) => { resolve = r }))
    render(
      <TranslationFields translations={[]} onCreate={onCreate}
        onUpdate={vi.fn()} onDelete={vi.fn()} />,
    )
    const input = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    resolve()
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1))
  })

  it('does not double-fire onDelete when Enter empties a field and blur follows before the commit resolves', async () => {
    let resolve!: () => void
    const onDelete = vi.fn(() => new Promise<void>((r) => { resolve = r }))
    render(
      <TranslationFields translations={[tr('T1', 'первый', true)]} onCreate={vi.fn()}
        onUpdate={vi.fn()} onDelete={onDelete} />,
    )
    const first = screen.getByDisplayValue('первый')
    fireEvent.change(first, { target: { value: '  ' } })
    fireEvent.keyDown(first, { key: 'Enter' })
    fireEvent.blur(first)
    resolve()
    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1))
  })
})
