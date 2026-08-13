import { render, screen, waitFor } from '@testing-library/react'
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
})
