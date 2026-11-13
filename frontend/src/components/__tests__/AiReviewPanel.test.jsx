import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import AiReviewPanel from '../AiReviewPanel'

function baseReview(overrides = {}) {
  return {
    id: 10,
    xunji_name: '杠铃卧推',
    verdict: 'current_ok',
    suggested_category: null,
    suggested_exercise_name: null,
    reason: '当前映射与目录一致',
    model: 'test-model',
    batch_id: 'batch-1',
    resolved: false,
    created_at: '2026-11-13T00:00:00Z',
    ...overrides,
  }
}

describe('AiReviewPanel', () => {
  it('test_current_ok_badge', () => {
    render(<AiReviewPanel review={baseReview({ verdict: 'current_ok' })} onApply={vi.fn()} />)
    const panel = screen.getByTestId('ai-review-panel')
    expect(panel).toHaveAttribute('data-verdict', 'current_ok')
    expect(panel).toHaveTextContent('当前映射合理')
    expect(screen.queryByTestId('ai-review-apply')).not.toBeInTheDocument()
  })

  it('test_better_candidate_shows_suggestion', () => {
    render(
      <AiReviewPanel
        review={baseReview({
          verdict: 'better_candidate',
          suggested_category: 'BENCH_PRESS',
          suggested_exercise_name: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS',
          reason: '中立握更贴合动作',
        })}
        onApply={vi.fn()}
      />,
    )
    const panel = screen.getByTestId('ai-review-panel')
    expect(panel).toHaveTextContent('有更优候选')
    expect(panel).toHaveTextContent('BENCH_PRESS/NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS')
  })

  it('test_better_candidate_apply_calls_back', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    render(
      <AiReviewPanel
        review={baseReview({
          verdict: 'better_candidate',
          suggested_category: 'BENCH_PRESS',
          suggested_exercise_name: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS',
        })}
        onApply={onApply}
      />,
    )
    await user.click(screen.getByTestId('ai-review-apply'))
    expect(onApply).toHaveBeenCalledWith({
      category: 'BENCH_PRESS',
      exercise_name: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS',
    })
  })

  it('test_suspected_error_badge', () => {
    render(
      <AiReviewPanel
        review={baseReview({
          verdict: 'suspected_error',
          suggested_category: 'FLY',
          suggested_exercise_name: 'DUMBBELL_FLY',
        })}
        onApply={vi.fn()}
      />,
    )
    expect(screen.getByTestId('ai-review-panel')).toHaveTextContent('疑似错误')
  })

  it('test_likely_unmapped_badge', () => {
    render(
      <AiReviewPanel
        review={baseReview({ verdict: 'likely_unmapped', reason: '目录无近似项' })}
        onApply={vi.fn()}
      />,
    )
    expect(screen.getByTestId('ai-review-panel')).toHaveTextContent('可能无对应')
    expect(screen.queryByTestId('ai-review-apply')).not.toBeInTheDocument()
  })

  it('test_needs_human_badge', () => {
    render(
      <AiReviewPanel
        review={baseReview({ verdict: 'needs_human', reason: '语义歧义较大' })}
        onApply={vi.fn()}
      />,
    )
    expect(screen.getByTestId('ai-review-panel')).toHaveTextContent('需要你判断')
  })

  it('test_reason_rendered', () => {
    render(
      <AiReviewPanel
        review={baseReview({ reason: '这是一条完整的审核理由，不应被截断。' })}
        onApply={vi.fn()}
      />,
    )
    expect(screen.getByText('这是一条完整的审核理由，不应被截断。')).toBeInTheDocument()
  })

  it('test_apply_button_hidden_without_suggestion', () => {
    render(
      <AiReviewPanel
        review={baseReview({
          verdict: 'better_candidate',
          suggested_category: 'BENCH_PRESS',
          suggested_exercise_name: '',
          reason: '有方向但缺具体动作',
        })}
        onApply={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('ai-review-apply')).not.toBeInTheDocument()
  })
})
