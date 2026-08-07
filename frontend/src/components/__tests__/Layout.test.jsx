import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Layout from '../Layout'

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
  })
})
