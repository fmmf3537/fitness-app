import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { CurrentUserProvider } from '../../contexts/CurrentUserContext'
import LeaderboardPage from '../LeaderboardPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const ENTRIES = {
  metric: 'frequency',
  window: '7d',
  computed_at: '2026-08-25T23:30:00',
  entries: [
    { user_id: 1, username: 'alice', value: 5, rank: 1 },
    { user_id: 2, username: 'bob', value: 3, rank: 2 },
  ],
  from_cache: true,
}

function renderPage(initial = '/leaderboard?metric=frequency&window=7d') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <CurrentUserProvider>
        <Routes>
          <Route path="/leaderboard" element={<LeaderboardPage />} />
        </Routes>
      </CurrentUserProvider>
    </MemoryRouter>,
  )
}

describe('LeaderboardPage', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('fh_token', 'tok')
    localStorage.setItem('fh_user_id', '1')
    localStorage.setItem('fh_user_role', 'user')
  })

  it('切换 metric tab 重新请求', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn((url) => {
      if (String(url).includes('metric=volume')) {
        return Promise.resolve(mockResponse({ ...ENTRIES, metric: 'volume' }))
      }
      return Promise.resolve(mockResponse(ENTRIES))
    })
    renderPage()
    await screen.findByTestId('leaderboard-table')
    await user.click(screen.getByTestId('metric-tab-volume'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('metric=volume'),
        expect.anything(),
      )
    })
  })

  it('切换 window tab', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn((url) => Promise.resolve(mockResponse(ENTRIES)))
    renderPage()
    await screen.findByTestId('leaderboard-table')
    await user.click(screen.getByTestId('window-tab-30d'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('window=30d'),
        expect.anything(),
      )
    })
  })

  it('当前用户行高亮置顶', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(ENTRIES)))
    renderPage()
    const card = await screen.findByTestId('my-rank-card')
    expect(card.textContent).toContain('alice')
    expect(card.textContent).toContain('#1')
  })

  it('400 错误显示', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'bad' }, 400)))
    renderPage('/leaderboard?metric=frequency&window=7d')
    expect(await screen.findByRole('alert')).toHaveTextContent('参数无效')
  })
})
