import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkoutDetailPage from '../WorkoutDetailPage'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const WORKOUT = {
  id: 1,
  date: '2026-08-03',
  title: '胸部训练',
  match_status: 'auto_matched',
  tags: 'strength_training',
  duration_s: 3600,
  calories: 350,
  avg_hr: 120,
  max_hr: 158,
  movements: [
    {
      name: '卧推',
      sets: [{ weight: 60, unit: 'kg', reps: 10, time: 0, done: true, rpe: 8 }],
    },
  ],
  heart_rate: [
    { t: 1754, hr: 118 },
    { t: 1755, hr: 122 },
  ],
  xunji_raw: { source: 'xunji', foo: 'bar' },
  garmin_raw: { source: 'garmin', activity_id: 'g1' },
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/workouts/1']}>
      <Routes>
        <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkoutDetailPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(WORKOUT)))
  })

  it('渲染摘要数据', async () => {
    renderPage()
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('1 小时')).toBeInTheDocument()
    expect(screen.getByText('350 千卡')).toBeInTheDocument()
    expect(screen.getByText('120 bpm')).toBeInTheDocument()
    expect(screen.getByText('158 bpm')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/workouts/1',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('融合标签页显示组次表和心率图', async () => {
    renderPage()
    expect(await screen.findByText('卧推')).toBeInTheDocument()
    expect(screen.getByText(/60\s*kg\s*×\s*10/)).toBeInTheDocument()
    expect(screen.getByText('RPE 8')).toBeInTheDocument()
    expect(screen.getByTestId('hr-chart')).toBeInTheDocument()
    // 窄屏可横向滚动：组次表外层包 overflow-x-auto 容器
    const table = screen.getByRole('table')
    expect(table.parentElement).toHaveClass('overflow-x-auto')
  })

  it('切换到训记原始 / 佳明原始标签', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('卧推')

    await user.click(screen.getByRole('tab', { name: '训记原始' }))
    expect(screen.getByTestId('xunji-raw').textContent).toContain('"foo"')
    expect(screen.queryByText('卧推')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '佳明原始' }))
    expect(screen.getByTestId('garmin-raw').textContent).toContain('"g1"')

    await user.click(screen.getByRole('tab', { name: '融合' }))
    expect(screen.getByText('卧推')).toBeInTheDocument()
  })

  it('无心率数据时显示提示', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ ...WORKOUT, heart_rate: null })),
    )
    renderPage()
    expect(await screen.findByText('无心率数据')).toBeInTheDocument()
  })
})
