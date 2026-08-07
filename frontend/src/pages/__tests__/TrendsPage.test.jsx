import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TrendsPage from '../TrendsPage'

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

const TRENDS = {
  weeks: 4,
  weekly_volume: [{ week_start: '2026-07-13', volume_tons: 12.34, sessions: 3 }],
  body_part_frequency: [{ week_start: '2026-07-13', parts: { 胸: 2, 背: 1 } }],
  body_metrics: {
    weight: [{ date: '2026-07-15', value: 72.4 }],
    bodyfat: [{ date: '2026-07-15', value: 18.2 }],
  },
  sleep_volume: [{ date: '2026-07-15', sleep_hours: 7.2, volume_tons: 4.1 }],
}

const EMPTY_TRENDS = {
  weeks: 4,
  weekly_volume: [],
  body_part_frequency: [],
  body_metrics: { weight: [], bodyfat: [] },
  sleep_volume: [],
}

describe('TrendsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(TRENDS)))
  })

  it('默认按 4 周拉取并渲染四张图', async () => {
    render(<TrendsPage />)
    expect(await screen.findByTestId('trend-chart-volume')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-bodypart')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-bodymetric')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-sleep')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/trends?weeks=4',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    expect(screen.getByText('每周总容量（吨）')).toBeInTheDocument()
    expect(screen.getByText('各部位训练频次')).toBeInTheDocument()
    expect(screen.getByText('体重/体脂曲线')).toBeInTheDocument()
    expect(screen.getByText('睡眠-容量散点')).toBeInTheDocument()
  })

  it('切换 12 周触发新请求', async () => {
    const user = userEvent.setup()
    render(<TrendsPage />)
    await screen.findByTestId('trend-chart-volume')

    await user.click(screen.getByTestId('weeks-toggle-12'))

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/stats/trends?weeks=12',
        expect.any(Object),
      )
    })

    await user.click(screen.getByTestId('weeks-toggle-4'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/stats/trends?weeks=4',
        expect.any(Object),
      )
    })
  })

  it('空数据不崩溃', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(EMPTY_TRENDS)))
    render(<TrendsPage />)
    expect(await screen.findByTestId('trend-chart-volume')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-sleep')).toBeInTheDocument()
  })

  it('加载失败显示错误提示', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'boom' }, 500)))
    render(<TrendsPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
