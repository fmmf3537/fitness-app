import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import BottomTabs from '../BottomTabs'
import { installMatchMedia } from '../../test/mockMatchMedia'

function renderTabs(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <BottomTabs />
    </MemoryRouter>,
  )
}

describe('BottomTabs 移动端底部 Tab 栏', () => {
  beforeEach(() => {
    installMatchMedia(true)
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  it('渲染五个 Tab 及正确 href，每个 Tab 含图标', () => {
    renderTabs()
    const nav = screen.getByTestId('bottom-tabs')
    const tabs = [
      ['训练日历', '/'],
      ['训练计划', '/plans'],
      ['AI报告', '/ai-reports'],
      ['趋势', '/trends'],
      ['我的', '/settings'],
    ]
    for (const [name, href] of tabs) {
      const link = within(nav).getByRole('link', { name })
      expect(link).toHaveAttribute('href', href)
      expect(link.querySelector('svg')).not.toBeNull()
    }
  })

  it('激活态 text-indigo-600，未激活 text-gray-500', () => {
    renderTabs('/trends')
    const nav = screen.getByTestId('bottom-tabs')
    expect(within(nav).getByRole('link', { name: '趋势' })).toHaveClass('text-indigo-600')
    expect(within(nav).getByRole('link', { name: '训练日历' })).toHaveClass('text-gray-500')
    expect(within(nav).getByRole('link', { name: '我的' })).toHaveClass('text-gray-500')
  })

  it('根路由 / 精确匹配激活（/workouts 不激活训练日历）', () => {
    renderTabs('/workouts')
    const nav = screen.getByTestId('bottom-tabs')
    expect(within(nav).getByRole('link', { name: '训练日历' })).toHaveClass('text-gray-500')
  })

  it('fixed 底部定位 + 底部安全区 padding class', () => {
    renderTabs()
    const nav = screen.getByTestId('bottom-tabs')
    expect(nav.className).toContain('fixed')
    expect(nav.className).toContain('bottom-0')
    expect(nav.className).toContain('pb-[env(safe-area-inset-bottom)]')
  })

  it('桌面断点（≥md）不渲染', () => {
    installMatchMedia(false)
    renderTabs()
    expect(screen.queryByTestId('bottom-tabs')).not.toBeInTheDocument()
  })
})
