import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import BottomSheet from '../BottomSheet'

describe('BottomSheet', () => {
  it('open=false 时不渲染任何内容', () => {
    render(
      <BottomSheet open={false} onClose={() => {}} title="标题">
        <p>正文</p>
      </BottomSheet>,
    )
    expect(screen.queryByTestId('bottom-sheet')).not.toBeInTheDocument()
    expect(screen.queryByText('正文')).not.toBeInTheDocument()
  })

  it('打开时渲染标题/内容/底部操作区插槽，并锁定 body 滚动', () => {
    const { unmount } = render(
      <BottomSheet
        open
        onClose={() => {}}
        title="报告标题"
        footer={<button type="button">上一篇</button>}
      >
        <p>正文内容</p>
      </BottomSheet>,
    )
    expect(screen.getByTestId('bottom-sheet')).toBeInTheDocument()
    expect(screen.getByText('报告标题')).toBeInTheDocument()
    expect(screen.getByText('正文内容')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上一篇' })).toBeInTheDocument()
    // body 滚动锁：打开时 hidden，卸载后恢复
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('点击半透明背板触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <BottomSheet open onClose={onClose} title="t">
        <p>x</p>
      </BottomSheet>,
    )
    await user.click(screen.getByTestId('bottom-sheet-backdrop'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('点击右上角关闭按钮触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <BottomSheet open onClose={onClose} title="t">
        <p>x</p>
      </BottomSheet>,
    )
    await user.click(screen.getByTestId('bottom-sheet-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('抽屉容器/内容区/footer 具备防撑破与高度兜底 class（移动端真机缺陷修复）', () => {
    render(
      <BottomSheet
        open
        onClose={() => {}}
        title="t"
        footer={<button type="button">下一篇</button>}
      >
        <p>正文</p>
      </BottomSheet>,
    )
    // 抽屉容器：min-w-0 防内容撑宽；max-h vh + dvh 兜底链
    const sheet = screen.getByTestId('bottom-sheet')
    expect(sheet.className).toContain('min-w-0')
    expect(sheet.className).toContain('max-h-[85vh]')
    expect(sheet.className).toContain('max-h-[85dvh]')
    // 内容滚动区：min-w-0 + 横向隐藏溢出
    const content = screen.getByTestId('bottom-sheet-content')
    expect(content.className).toContain('min-w-0')
    expect(content.className).toContain('overflow-y-auto')
    expect(content.className).toContain('overflow-x-hidden')
    // footer：shrink-0 保证任何高度下可见
    const footer = screen.getByTestId('bottom-sheet-footer')
    expect(footer.className).toContain('shrink-0')
  })

  it('点击内容区不触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <BottomSheet open onClose={onClose} title="t">
        <p>正文内容</p>
      </BottomSheet>,
    )
    await user.click(screen.getByText('正文内容'))
    expect(onClose).not.toHaveBeenCalled()
  })
})
