import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Layout from '../Layout'
import BottomTabs from '../BottomTabs'
import Card from '../ui/Card'
import { applyDarkClass, initDarkModeListener } from '../../utils/darkMode'
import { installMatchMedia } from '../../test/mockMatchMedia'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

afterEach(() => {
  applyDarkClass(false)
  installMatchMedia(false)
})

describe('initDarkModeListener', () => {
  it('matchMedia dark=true 时 html 有 dark 类；切换后移除；cleanup 移除监听', () => {
    const mq = installMatchMedia(true)
    const cleanup = initDarkModeListener()
    expect(document.documentElement).toHaveClass('dark')

    mq.setMatches(false)
    expect(document.documentElement).not.toHaveClass('dark')

    cleanup()
    mq.setMatches(true)
    expect(document.documentElement).not.toHaveClass('dark')
  })
})

describe('暗色类映射抽查', () => {
  it('Card 渲染含 dark:bg-gray-900', () => {
    render(<Card testId="dark-card">x</Card>)
    expect(screen.getByTestId('dark-card')).toHaveClass('dark:bg-gray-900')
  })

  it('Layout 根含 dark:bg-gray-950', () => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ candidates: [] })))
    const { container } = render(
      <MemoryRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(container.firstChild).toHaveClass('dark:bg-gray-950')
  })

  it('BottomTabs 含 dark:bg-gray-900', () => {
    installMatchMedia(true)
    render(
      <MemoryRouter>
        <BottomTabs />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('bottom-tabs')).toHaveClass('dark:bg-gray-900')
  })
})
