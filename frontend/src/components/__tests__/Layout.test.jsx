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
    // 桌面端不渲染汉堡按钮与底部 Tab 栏
    expect(screen.queryByTestId('nav-toggle')).not.toBeInTheDocument()
    expect(screen.queryByTestId('bottom-tabs')).not.toBeInTheDocument()
  })
})

describe('Layout 移动端汉堡菜单与底部 Tab', () => {
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
            <Route path="/reviews" element={<div>reviews</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('移动端渲染底部 Tab 栏，汉堡按钮位于头部右侧容器最右（右上角）', () => {
    renderLayout()
    expect(screen.getByTestId('bottom-tabs')).toBeInTheDocument()
    expect(screen.getByTestId('nav-toggle')).toBeInTheDocument()
    // 汉堡按钮是头部右侧容器最后一个元素 → 视觉右上角
    const toggle = screen.getByTestId('nav-toggle')
    expect(toggle.parentElement.lastElementChild).toBe(toggle)
  })

  it('移动端默认收起汉堡菜单，主内容区加底部 padding 防 Tab 遮挡', () => {
    renderLayout()
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
    expect(screen.getByRole('main').className).toMatch(/pb-24/)
  })

  it('汉堡菜单仅含次级入口，五个 Tab 主入口不在其中', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(screen.getByTestId('nav-toggle'))
    const menu = screen.getByTestId('mobile-nav')
    const secondary = [
      ['待确认队列', '/candidates'],
      ['复盘中心', '/reviews'],
      ['身体数据', '/body-metrics'],
      ['截图导入', '/screenshot-import'],
      ['文件导入', '/fit-import'],
      ['历史补录', '/backfill'],
    ]
    for (const [name, href] of secondary) {
      expect(within(menu).getByRole('link', { name })).toHaveAttribute('href', href)
    }
    for (const name of ['训练日历', '训练计划', 'AI报告', '趋势', '我的']) {
      expect(within(menu).queryByRole('link', { name })).not.toBeInTheDocument()
    }
  })

  it('点击汉堡按钮展开/收起菜单', async () => {
    const user = userEvent.setup()
    renderLayout()
    const toggle = screen.getByTestId('nav-toggle')

    await user.click(toggle)
    expect(screen.getByTestId('mobile-nav')).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(toggle)
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
  })

  it('选中菜单项后自动收起菜单', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(screen.getByTestId('nav-toggle'))
    await user.click(within(screen.getByTestId('mobile-nav')).getByRole('link', { name: '复盘中心' }))
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument()
  })

  it('头部加顶部安全区 padding（沉浸式状态栏）', () => {
    renderLayout()
    const header = screen.getByRole('banner')
    expect(header.className).toContain('pt-[env(safe-area-inset-top)]')
  })
})
