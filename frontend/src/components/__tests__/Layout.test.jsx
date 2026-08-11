import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Layout from '../Layout'
import { installMatchMedia } from '../../test/mockMatchMedia'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

describe('Layout 导航', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ candidates: [] })))
  })

  it('包含全部页面导航链接', async () => {
    render(
      <MemoryRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    const links = [
      ['训练日历', '/'],
      ['待确认队列', '/candidates'],
      ['AI 报告', '/ai-reports'],
      ['趋势', '/trends'],
      ['导入', '/backfill'],
      ['设置', '/settings'],
    ]
    for (const [name, href] of links) {
      const link = await screen.findByRole('link', { name })
      expect(link).toHaveAttribute('href', href)
    }
    // 桌面端不渲染汉堡按钮
    expect(screen.queryByTestId('nav-toggle')).not.toBeInTheDocument()
  })
})

describe('Layout 移动端汉堡菜单', () => {
  beforeEach(() => {
    installMatchMedia(true)
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ candidates: [] })))
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  function renderLayout() {
    return render(
      <MemoryRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div>home</div>} />
            <Route path="/trends" element={<div>trends</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('移动端默认收起竖向菜单，横向导航不渲染', async () => {
    renderLayout()
    expect(screen.getByTestId('nav-toggle')).toBeInTheDocument()
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '训练日历' })).not.toBeInTheDocument()
  })

  it('点击汉堡按钮展开/收起竖向菜单', async () => {
    const user = userEvent.setup()
    renderLayout()
    const toggle = screen.getByTestId('nav-toggle')

    await user.click(toggle)
    const menu = screen.getByTestId('mobile-nav')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(within(menu).getByRole('link', { name: '训练日历' })).toBeInTheDocument()
    expect(within(menu).getByRole('link', { name: '设置' })).toBeInTheDocument()

    await user.click(toggle)
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
  })

  it('选中菜单项后自动收起菜单', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(screen.getByTestId('nav-toggle'))
    await user.click(within(screen.getByTestId('mobile-nav')).getByRole('link', { name: '趋势' }))
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
  })
})
