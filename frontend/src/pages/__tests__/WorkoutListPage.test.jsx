import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkoutListPage from '../WorkoutListPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const CALENDAR = {
  month: '2026-08',
  days: [
    {
      date: '2026-08-03',
      workouts: [
        { id: 1, title: '胸部训练', match_status: 'auto_matched' },
        { id: 2, title: '跑步', match_status: 'pending' },
      ],
    },
  ],
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/workouts" element={<WorkoutListPage />} />
        <Route path="/" element={<div>日历首页</div>} />
        <Route path="/workouts/:id" element={<div>详情页</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkoutListPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(CALENDAR)))
  })

  it('无 date 参数时显示 EmptyState 兜底', async () => {
    renderAt('/workouts')
    expect(await screen.findByTestId('no-date')).toBeInTheDocument()
    expect(screen.getByText('未指定日期')).toBeInTheDocument()
    expect(screen.getByText('请从训练日历选择一天查看')).toBeInTheDocument()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('加载中显示骨架屏', async () => {
    let resolveFetch
    globalThis.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }),
    )
    renderAt('/workouts?date=2026-08-03')
    // 骨架：3 个 animate-pulse 条
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThanOrEqual(3)
    resolveFetch(mockResponse(CALENDAR))
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
  })

  it('加载失败显示 ErrorState，点击重试重新请求', async () => {
    const user = userEvent.setup()
    let calls = 0
    globalThis.fetch = vi.fn(() => {
      calls += 1
      if (calls === 1) return Promise.resolve(mockResponse({}, 500))
      return Promise.resolve(mockResponse(CALENDAR))
    })
    renderAt('/workouts?date=2026-08-03')

    const alert = await screen.findByTestId('list-error')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveTextContent('加载失败')

    await user.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
  })

  it('当日无记录显示 EmptyState', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ month: '2026-08', days: [] })),
    )
    renderAt('/workouts?date=2026-08-03')
    expect(await screen.findByText('当日没有训练记录')).toBeInTheDocument()
    expect(screen.getByText(/换个日期看看/)).toBeInTheDocument()
  })

  it('渲染列表项与 Badge 状态，点击进入详情', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(CALENDAR)))
    renderAt('/workouts?date=2026-08-03')

    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('跑步')).toBeInTheDocument()
    expect(screen.getByText('自动匹配')).toBeInTheDocument()
    expect(screen.getByText('待确认')).toBeInTheDocument()
    expect(screen.getByText('2026-08-03 训练')).toBeInTheDocument()

    await user.click(screen.getByText('胸部训练'))
    expect(await screen.findByText('详情页')).toBeInTheDocument()
  })
})
