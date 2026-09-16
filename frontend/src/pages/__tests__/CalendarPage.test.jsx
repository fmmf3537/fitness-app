import { render as renderUI, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CalendarPage from '../CalendarPage'
import { SyncTaskContext } from '../../components/useSyncTask'
import { CandidateQueueContext } from '../../components/useCandidateQueue'

// Calendar unit tests isolate the shared task state; lifecycle coverage lives in SyncButton tests.
function render(ui, queue = { candidates: [], pendingCount: 0, error: '', loading: false }) {
  return renderUI(
    <SyncTaskContext.Provider
      value={{ task: { running: false, status: null }, revision: 0 }}
    >
      <CandidateQueueContext.Provider
        value={queue}
      >
        {ui}
      </CandidateQueueContext.Provider>
    </SyncTaskContext.Provider>,
  )
}

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const CALENDAR_AUG = {
  month: '2026-08',
  days: [
    {
      date: '2026-08-03',
      workouts: [
        { id: 1, title: '胸部训练', match_status: 'auto_matched', tags: 'strength_training' },
      ],
    },
    {
      date: '2026-08-10',
      workouts: [
        { id: 2, title: '跑步', match_status: 'pending', tags: 'running' },
      ],
    },
  ],
}

const CALENDAR_SEP = { month: '2026-09', days: [] }

describe('CalendarPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn((url) => {
      if (String(url).includes('month=2026-09')) return Promise.resolve(mockResponse(CALENDAR_SEP))
      return Promise.resolve(mockResponse(CALENDAR_AUG))
    })
  })

  it('标记有训练的日期', async () => {
    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    await screen.findByTestId('day-2026-08-03')
    expect(screen.getByTestId('dot-2026-08-03-auto_matched')).toBeInTheDocument()
    expect(screen.getByTestId('dot-2026-08-10-pending')).toHaveClass('bg-amber-500')
    expect(screen.getByTestId('dot-2026-08-03-auto_matched')).toHaveClass('bg-green-500')
    expect(screen.getByText('已匹配')).toBeInTheDocument()
    expect(screen.getByText('仅单源')).toBeInTheDocument()
    expect(screen.getAllByText('待确认').length).toBeGreaterThan(0)
    expect(screen.queryByText('手动匹配')).not.toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/workouts/calendar?month=2026-08',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('有待确认记录时显示真实数量和处理入口', async () => {
    render(
      <MemoryRouter><CalendarPage initialMonth="2026-08" /></MemoryRouter>,
      { candidates: [{ id: 1 }, { id: 2 }], pendingCount: 2, error: '', loading: false },
    )
    expect(await screen.findByText('2 条记录待确认')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /去处理/ })).toHaveAttribute('href', '/candidates')
  })

  it('候选初次加载失败不伪装成 0', async () => {
    render(
      <MemoryRouter><CalendarPage initialMonth="2026-08" /></MemoryRouter>,
      { candidates: null, pendingCount: null, error: 'offline', loading: false },
    )
    expect(await screen.findByText('待确认数量暂时无法刷新')).toBeInTheDocument()
    expect(screen.queryByText(/条记录待确认/)).not.toBeInTheDocument()
  })

  it('翻月按钮触发新月份请求', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    await screen.findByTestId('day-2026-08-03')
    await user.click(screen.getByRole('button', { name: '下个月' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/workouts/calendar?month=2026-09',
        expect.anything(),
      )
    })
    expect(screen.getByTestId('current-month')).toHaveTextContent('2026 年 09 月')
  })

  describe('头部响应式布局（V3-10）', () => {
    async function renderHeader() {
      render(
        <MemoryRouter>
          <CalendarPage initialMonth="2026-08" />
        </MemoryRouter>,
      )
      await screen.findByTestId('day-2026-08-03')
      return screen.getByTestId('calendar-header')
    }

    it('月份标题禁止折行（whitespace-nowrap + shrink-0）', async () => {
      await renderHeader()
      const title = screen.getByTestId('current-month')
      expect(title).toHaveClass('whitespace-nowrap')
      expect(title).toHaveClass('shrink-0')
    })

    it('同步按钮保持紧凑并固定在标题右侧', async () => {
      await renderHeader()
      const syncRow = screen.getByTestId('sync-row')
      expect(syncRow).toHaveClass('shrink-0')
      expect(screen.getByRole('button', { name: '上个月' })).toHaveTextContent('‹')
      expect(screen.getByRole('button', { name: '下个月' })).toHaveTextContent('›')
    })

    it('头部使用单行紧凑布局', async () => {
      const header = await renderHeader()
      expect(header).toHaveClass('flex')
      expect(header).toHaveClass('items-center')
      expect(header).toHaveClass('justify-between')
      expect(header).toHaveClass('gap-2')
    })
  })

  it('加载失败显示 ErrorState 且不渲染日历网格', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({}, 500)))
    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    const alert = await screen.findByTestId('calendar-error')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveTextContent('加载失败：request failed: 500')
    expect(document.querySelectorAll('[data-testid^="day-"]')).toHaveLength(0)
    expect(screen.queryByText('已匹配')).not.toBeInTheDocument()
  })

  it('错误态点击重试重新发起请求', async () => {
    const user = userEvent.setup()
    let calls = 0
    globalThis.fetch = vi.fn(() => {
      calls += 1
      if (calls === 1) return Promise.resolve(mockResponse({}, 500))
      return Promise.resolve(mockResponse(CALENDAR_AUG))
    })

    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    await screen.findByTestId('calendar-error')
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: '重试' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    })
    await screen.findByTestId('day-2026-08-03')
    expect(screen.queryByTestId('calendar-error')).not.toBeInTheDocument()
  })
})
