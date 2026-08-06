import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AIReportsPage from '../AIReportsPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const REPORTS = {
  reports: [
    {
      id: 1,
      type: 'session_review',
      workout_id: 10,
      date: '2026-08-03',
      workout_title: '胸部训练',
      model: 'deepseek-chat',
      prompt_tokens: 120,
      completion_tokens: 30,
      cost_estimate: 0.0003,
      content_md: '## 完成质量\n训练完成度较高\n## 与历史对比\n卧推重量持平',
      created_at: '2026-08-03T23:00:00',
    },
    {
      id: 2,
      type: 'session_review',
      workout_id: 11,
      date: '2026-08-03',
      workout_title: '背部训练',
      model: 'deepseek-chat',
      prompt_tokens: 110,
      completion_tokens: 25,
      cost_estimate: 0.00025,
      content_md: '## 完成质量\n背部训练完整',
      created_at: '2026-08-03T23:05:00',
    },
  ],
}

const EMPTY_REPORTS = { reports: [] }

describe('AIReportsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(REPORTS)))
    // 固定日期为 2026-08-03，避免输入默认值随运行时间变化
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-03T12:00:00'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('默认加载当天报告列表', async () => {
    render(<AIReportsPage />)
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('背部训练')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports?date=2026-08-03',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('切换日期会重新拉取数据', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    const input = screen.getByTestId('date-input')
    await user.clear(input)
    await user.type(input, '2026-08-01')

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?date=2026-08-01',
        expect.any(Object),
      )
    })
  })

  it('点击报告卡片显示 Markdown 详情', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('report-card-1'))

    expect(await screen.findByRole('heading', { name: '完成质量' })).toBeInTheDocument()
    expect(screen.getByText('训练完成度较高')).toBeInTheDocument()
    const detail = screen.getByTestId('report-detail')
    expect(detail.textContent).toContain('模型：deepseek-chat')
    expect(detail.textContent).toContain('120')
    expect(detail.textContent).toContain('30')
  })

  it('无报告时显示空状态', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(EMPTY_REPORTS)))
    render(<AIReportsPage />)
    expect(await screen.findByText('当日暂无 AI 点评')).toBeInTheDocument()
  })

  it('请求失败显示错误信息', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'bad request' }, 500)))
    render(<AIReportsPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
