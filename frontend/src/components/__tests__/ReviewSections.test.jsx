import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ReviewSections from '../ReviewSections'

vi.mock('echarts', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}))

describe('ReviewSections', () => {
  it('≥2 个 h2 时按标题切成多卡', () => {
    render(
      <ReviewSections
        text={'## 本周概览\n完成 4 次训练。\n## 下周建议\n深蹲加 2.5kg'}
      />,
    )
    const cards = screen.getAllByTestId('review-section-card')
    expect(cards).toHaveLength(2)
    expect(screen.getByTestId('review-sections')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '本周概览' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '下周建议' })).toBeInTheDocument()
    expect(cards[0]).toHaveTextContent('本周概览')
    expect(cards[0]).toHaveTextContent('完成 4 次训练。')
    expect(cards[1]).toHaveTextContent('下周建议')
    expect(cards[1]).toHaveTextContent('深蹲加 2.5kg')
  })

  it('无 h2 时回退单卡且全文不丢', () => {
    const text = '本周训练 3 次，没有二级标题。\n容量 4520 kg。'
    render(<ReviewSections text={text} />)
    const cards = screen.getAllByTestId('review-section-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveTextContent('本周训练 3 次，没有二级标题。')
    expect(cards[0]).toHaveTextContent('容量 4520 kg。')
  })

  it('仅 1 个 h2 时回退单卡且全文不丢', () => {
    const text = '前言一句。\n## 本周概览\n只有一个标题。'
    render(<ReviewSections text={text} />)
    const cards = screen.getAllByTestId('review-section-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveTextContent('前言一句。')
    expect(cards[0]).toHaveTextContent('本周概览')
    expect(cards[0]).toHaveTextContent('只有一个标题。')
  })

  it('echarts 围栏归属到所在 h2 卡片，不被切断', () => {
    const text =
      '## 本周概览\n概览正文\n```echarts\n{"series":[{"type":"pie"}]}\n```\n' +
      '## 下周建议\n卧推加到 62.5kg'
    render(<ReviewSections text={text} />)
    const cards = screen.getAllByTestId('review-section-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].querySelector('[data-testid="echarts-block"]')).toBeTruthy()
    expect(cards[1].querySelector('[data-testid="echarts-block"]')).toBeFalsy()
    expect(cards[0]).toHaveTextContent('本周概览')
    expect(cards[0]).toHaveTextContent('概览正文')
    expect(cards[1]).toHaveTextContent('下周建议')
    expect(cards[1]).toHaveTextContent('卧推加到 62.5kg')
  })
})
