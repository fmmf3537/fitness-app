import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import Onboarding from '../Onboarding'

function Location() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

describe('Onboarding', () => {
  beforeEach(() => localStorage.removeItem('fh_onboarding_v1_done'))

  it('首次访问完成三步后记录状态并跳转到真实趋势页', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><Onboarding /><Location /></MemoryRouter>)

    expect(await screen.findByRole('dialog')).toHaveTextContent('先连接 AI 教练')
    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('同步真实训练')
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '查看趋势' }))

    expect(localStorage.getItem('fh_onboarding_v1_done')).toBe('1')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/trends')
  })

  it('已完成时不再出现，首次引导可用 Escape 关闭并持久化', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<MemoryRouter><Onboarding /></MemoryRouter>)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(localStorage.getItem('fh_onboarding_v1_done')).toBe('1')

    rerender(<MemoryRouter><Onboarding /></MemoryRouter>)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
