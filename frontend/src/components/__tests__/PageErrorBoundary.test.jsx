import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PageErrorBoundary from '../PageErrorBoundary'

function BrokenPage() {
  throw new Error('render failed')
}

describe('PageErrorBoundary', () => {
  it('页面渲染失败时提供恢复入口，避免整页白屏', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<PageErrorBoundary><BrokenPage /></PageErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('页面暂时无法显示')
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回日历' })).toHaveAttribute('href', '/')
    vi.restoreAllMocks()
  })
})
