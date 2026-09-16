import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import NetworkStatus from '../NetworkStatus'

describe('NetworkStatus', () => {
  it('断网时提示同步不可用，恢复后自动移除提示', () => {
    render(<NetworkStatus />)
    act(() => window.dispatchEvent(new Event('offline')))
    expect(screen.getByRole('status')).toHaveTextContent('当前网络不可用')
    act(() => window.dispatchEvent(new Event('online')))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
