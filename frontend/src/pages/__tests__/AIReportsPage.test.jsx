import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AIReportsPage from '../AIReportsPage'
import { installMatchMedia } from '../../test/mockMatchMedia'

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

  it('默认进入最近报告模式，加载最近 50 条', async () => {
    render(<AIReportsPage />)
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('背部训练')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports?limit=50',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('切换到按日查询模式后加载当天报告列表', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('mode-bydate'))

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?date=2026-08-03',
        expect.any(Object),
      )
    })
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('背部训练')).toBeInTheDocument()
  })

  it('按日模式下切换日期会重新拉取数据', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')
    await user.click(screen.getByTestId('mode-bydate'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?date=2026-08-03',
        expect.any(Object),
      )
    })

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

  it('类型筛选切换改变请求参数（最近模式）', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('type-filter-advice'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?limit=50&type=next_advice',
        expect.any(Object),
      )
    })

    await user.click(screen.getByTestId('type-filter-session'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?limit=50&type=session_review',
        expect.any(Object),
      )
    })

    await user.click(screen.getByTestId('type-filter-all'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?limit=50',
        expect.any(Object),
      )
    })
  })

  it('类型筛选在按日模式下同样生效', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('mode-bydate'))
    await user.click(screen.getByTestId('type-filter-advice'))

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?date=2026-08-03&type=next_advice',
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

  it('按日模式无报告时显示空状态', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(EMPTY_REPORTS)))
    render(<AIReportsPage />)
    expect(await screen.findByText('暂无 AI 报告')).toBeInTheDocument()

    await user.click(screen.getByTestId('mode-bydate'))
    expect(await screen.findByText('当日暂无 AI 点评')).toBeInTheDocument()
  })

  it('请求失败显示错误信息', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'bad request' }, 500)))
    render(<AIReportsPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})

describe('AIReportsPage 移动端（底部抽屉）', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(REPORTS)))
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-03T12:00:00'))
    installMatchMedia(true)
  })

  afterEach(() => {
    installMatchMedia(false)
    vi.useRealTimers()
  })

  it('点击卡片弹出底部抽屉展示详情，不渲染桌面详情栏', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')
    // 未选中时无详情
    expect(screen.queryByTestId('report-detail')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('report-card-1'))

    expect(await screen.findByTestId('bottom-sheet')).toBeInTheDocument()
    expect(screen.getByTestId('report-detail')).toBeInTheDocument()
    expect(screen.getByText('训练完成度较高')).toBeInTheDocument()
    // 打开抽屉时锁定 body 滚动
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('抽屉内「上一篇/下一篇」在当前列表内切换，首尾禁用', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('report-card-1'))
    await screen.findByTestId('bottom-sheet')
    // 第一篇：上一篇禁用、下一篇可用
    expect(screen.getByTestId('sheet-prev')).toBeDisabled()
    expect(screen.getByTestId('sheet-next')).toBeEnabled()

    await user.click(screen.getByTestId('sheet-next'))
    expect(screen.getByText('背部训练完整')).toBeInTheDocument()
    // 末篇：下一篇禁用、上一篇可用
    expect(screen.getByTestId('sheet-next')).toBeDisabled()
    expect(screen.getByTestId('sheet-prev')).toBeEnabled()

    await user.click(screen.getByTestId('sheet-prev'))
    expect(screen.getByText('训练完成度较高')).toBeInTheDocument()
  })

  it('关闭按钮与背板均可收起抽屉并恢复 body 滚动', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AIReportsPage />)
    await screen.findByText('胸部训练')

    await user.click(screen.getByTestId('report-card-1'))
    await screen.findByTestId('bottom-sheet')
    await user.click(screen.getByTestId('bottom-sheet-close'))
    expect(screen.queryByTestId('bottom-sheet')).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('')

    await user.click(screen.getByTestId('report-card-2'))
    await screen.findByTestId('bottom-sheet')
    await user.click(screen.getByTestId('bottom-sheet-backdrop'))
    expect(screen.queryByTestId('bottom-sheet')).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('')
  })
})
