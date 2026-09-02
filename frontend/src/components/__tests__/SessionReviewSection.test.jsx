import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionReviewSection from '../SessionReviewSection'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const WORKOUT = { id: 10, date: '2026-08-03', title: '胸部训练' }

const REVIEW = {
  id: 5,
  type: 'session_review',
  workout_id: 10,
  date: '2026-08-03',
  workout_title: '胸部训练',
  content_md: '## 完成质量\n本次训练完成度高，组次全部完成。\n\n注意肩部热身。',
}

describe('SessionReviewSection', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('有点评时展示 Markdown 正文', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [REVIEW] })))
    render(<SessionReviewSection workout={WORKOUT} />)

    expect(await screen.findByText('本次训练点评')).toBeInTheDocument()
    expect(screen.getByText('完成质量')).toBeInTheDocument()
    expect(screen.getByText('本次训练完成度高，组次全部完成。')).toBeInTheDocument()
    expect(screen.getByText('注意肩部热身。')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports?date=2026-08-03&type=session_review',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('有点评时展示「分享海报」按钮（V3-5）', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [REVIEW] })))
    render(<SessionReviewSection workout={WORKOUT} />)
    expect(await screen.findByTestId('share-poster-btn')).toBeInTheDocument()
  })

  it('无点评时不渲染任何内容', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [] })))
    const { container } = render(<SessionReviewSection workout={WORKOUT} />)

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    await waitFor(() => expect(container).toBeEmptyDOMElement())
    expect(screen.queryByText('本次训练点评')).not.toBeInTheDocument()
  })

  it('报告中无本 workout 的点评时不渲染', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ reports: [{ ...REVIEW, workout_id: 999 }] })),
    )
    const { container } = render(<SessionReviewSection workout={WORKOUT} />)

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    await waitFor(() => expect(container).toBeEmptyDOMElement())
    expect(screen.queryByText('本次训练点评')).not.toBeInTheDocument()
  })

  // V4-6：详情页内嵌对话 + 重新生成
  it('报告加载后渲染内嵌对话区入口（chat-expand-btn）', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [REVIEW] })))
    render(<SessionReviewSection workout={WORKOUT} />)
    expect(await screen.findByText('本次训练点评')).toBeInTheDocument()
    expect(screen.getByTestId('chat-expand-btn')).toBeInTheDocument()
    expect(screen.getByTestId('regen-review-btn')).toBeInTheDocument()
  })

  it('点击「重新生成」后 confirm 取消则不发请求', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [REVIEW] })))
    render(<SessionReviewSection workout={WORKOUT} />)
    const btn = await screen.findByTestId('regen-review-btn')
    await user.click(btn)

    expect(window.confirm).toHaveBeenCalledWith(
      '将根据以上讨论重新生成点评并覆盖当前内容，确认继续？',
    )
    const regenCall = globalThis.fetch.mock.calls.find(([url, opts]) =>
      url?.includes?.('/regenerate_with_feedback') && opts?.method === 'POST',
    )
    expect(regenCall).toBeUndefined()
  })

  it('confirm 确认后调用 session_review regenerate 接口并刷新点评内容', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const NEW = {
      ...REVIEW,
      id: 99,
      content_md: '## 新点评\n根据讨论已重新生成。',
      one_liner: '新一句话',
    }
    let resolveRegen
    globalThis.fetch = vi.fn((url, opts = {}) => {
      if (opts?.method === 'POST' && url?.includes?.('/regenerate_with_feedback')) {
        return new Promise((resolve) => {
          resolveRegen = () => resolve(mockResponse({ report: NEW }))
        })
      }
      return Promise.resolve(mockResponse({ reports: [REVIEW] }))
    })

    render(<SessionReviewSection workout={WORKOUT} />)
    const btn = await screen.findByTestId('regen-review-btn')
    await user.click(btn)

    // 请求进行中：按钮禁用 + 文案「重新生成中…」
    expect(btn).toBeDisabled()
    expect(btn).toHaveTextContent('重新生成中…')

    const regenCall = globalThis.fetch.mock.calls.find(([url, opts]) =>
      url?.includes?.('/regenerate_with_feedback') && opts?.method === 'POST',
    )
    expect(regenCall[0]).toBe('/api/ai-reports/session_review/10/regenerate_with_feedback')

    // 放行响应
    resolveRegen()

    // 成功后：新 content_md 上屏 + 成功提示
    expect(await screen.findByText('根据讨论已重新生成。')).toBeInTheDocument()
    expect(screen.getByTestId('regen-success')).toHaveTextContent('已根据讨论重新生成')
    expect(screen.getByTestId('regen-review-btn')).not.toBeDisabled()
  })

  it('POST 429 时显示日限提示', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    globalThis.fetch = vi.fn((url, opts = {}) => {
      if (opts?.method === 'POST' && url?.includes?.('/regenerate_with_feedback')) {
        return Promise.resolve(mockResponse({}, 429))
      }
      return Promise.resolve(mockResponse({ reports: [REVIEW] }))
    })

    render(<SessionReviewSection workout={WORKOUT} />)
    await user.click(await screen.findByTestId('regen-review-btn'))

    const err = await screen.findByTestId('regen-error')
    expect(err.textContent).toContain('今日重生成次数已达上限')
  })
})
