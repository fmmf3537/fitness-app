import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Card from '../ui/Card'
import ConfirmDialog from '../ui/ConfirmDialog'
import EmptyState from '../ui/EmptyState'
import ErrorState from '../ui/ErrorState'
import PillGroup from '../ui/PillGroup'
import Skeleton, { SkeletonText } from '../ui/Skeleton'
import { ToastProvider } from '../ui/Toast'
import { useToast } from '../ui/useToast'

describe('Button', () => {
  it('primary 含 bg-indigo-600 与 min-h-[44px]', () => {
    render(<Button>保存</Button>)
    const btn = screen.getByRole('button', { name: '保存' })
    expect(btn).toHaveClass('bg-indigo-600')
    expect(btn).toHaveClass('min-h-[44px]')
  })

  it('secondary / danger / dangerSolid / ghost 各自关键类名', () => {
    const { rerender } = render(<Button variant="secondary">次</Button>)
    expect(screen.getByRole('button')).toHaveClass('border-gray-300')

    rerender(<Button variant="danger">危</Button>)
    const danger = screen.getByRole('button')
    expect(danger).toHaveClass('border-red-300')
    expect(danger.className).not.toMatch(/\bbg-red-600\b/)

    rerender(<Button variant="dangerSolid">实危</Button>)
    expect(screen.getByRole('button')).toHaveClass('bg-red-600')

    rerender(<Button variant="ghost">幽灵</Button>)
    expect(screen.getByRole('button')).toHaveClass('text-indigo-600')
  })

  it('disabled 含 disabled:opacity-50；fullWidth 含 w-full', () => {
    const { rerender } = render(<Button disabled>禁</Button>)
    expect(screen.getByRole('button')).toHaveClass('disabled:opacity-50')

    rerender(<Button fullWidth>宽</Button>)
    expect(screen.getByRole('button')).toHaveClass('w-full')
  })

  it('未知 variant 回退 primary', () => {
    render(<Button variant="nope">回退</Button>)
    expect(screen.getByRole('button')).toHaveClass('bg-indigo-600')
  })
})

describe('Card', () => {
  it('基础四件套类名', () => {
    render(<Card testId="card">内容</Card>)
    const el = screen.getByTestId('card')
    expect(el).toHaveClass('rounded-xl')
    expect(el).toHaveClass('border-gray-200')
    expect(el).toHaveClass('bg-white')
    expect(el).toHaveClass('shadow-sm')
  })
})

describe('Badge', () => {
  it('indigo / amber 变体类名；未知回退 gray', () => {
    const { rerender } = render(<Badge variant="indigo">I</Badge>)
    expect(screen.getByText('I')).toHaveClass('bg-indigo-100', 'text-indigo-700')

    rerender(<Badge variant="amber">A</Badge>)
    expect(screen.getByText('A')).toHaveClass('bg-amber-100', 'text-amber-800')

    rerender(<Badge variant="weird">G</Badge>)
    expect(screen.getByText('G')).toHaveClass('bg-gray-100', 'text-gray-600')
  })
})

describe('PillGroup', () => {
  const options = [
    { value: '4', label: '近 4 周' },
    { value: '12', label: '近 12 周' },
  ]

  it('渲染 options，激活项 aria-selected 与 bg-indigo-600', () => {
    render(<PillGroup options={options} value="4" onChange={() => {}} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[0]).toHaveClass('bg-indigo-600')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('点击触发 onChange 并传出对应 value', () => {
    const onChange = vi.fn()
    render(<PillGroup options={options} value="4" onChange={onChange} />)
    fireEvent.click(screen.getByRole('tab', { name: '近 12 周' }))
    expect(onChange).toHaveBeenCalledWith('12')
  })
})

describe('Skeleton', () => {
  it('Skeleton / SkeletonText 渲染 testId；lines=3 时 3 根条', () => {
    const { container } = render(
      <>
        <Skeleton testId="sk" className="h-4" />
        <SkeletonText lines={3} testId="skt" />
      </>,
    )
    expect(screen.getByTestId('sk')).toHaveClass('animate-pulse', 'bg-gray-200')
    expect(screen.getByTestId('skt')).toBeInTheDocument()
    expect(container.querySelectorAll('.h-3.animate-pulse')).toHaveLength(3)
  })
})

describe('ConfirmDialog', () => {
  it('open=false 不渲染', () => {
    render(
      <ConfirmDialog open={false} title="删？" onConfirm={() => {}} onCancel={() => {}} />,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('open 时 role=dialog 且标题正确；点背板 / Esc 调 onCancel', () => {
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="确认删除"
        description="不可恢复"
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('确认删除')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('confirm-dialog-backdrop'))
    expect(onCancel).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledTimes(2)
  })

  it('danger 时确认键含 bg-red-600；点确认调 onConfirm', () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        title="危险"
        danger
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    )
    const confirm = screen.getByTestId('confirm-dialog-confirm')
    expect(confirm).toHaveClass('bg-red-600')
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalled()
  })
})

function ToastProbe() {
  const { toast } = useToast()
  return (
    <button type="button" onClick={() => toast('已保存')}>
      触发
    </button>
  )
}

describe('Toast', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('包 Provider 后 toast 出现 role=status 文本，3s 后消失', () => {
    vi.useFakeTimers()
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '触发' }))
    expect(screen.getByRole('status')).toHaveTextContent('已保存')
    // 定时器回调触发 setState，需包 act() 让 React 同步刷新 DOM
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('useToast 在 Provider 外抛错', () => {
    expect(() => render(<ToastProbe />)).toThrow(
      'useToast must be used within ToastProvider',
    )
  })
})

describe('EmptyState', () => {
  it('渲染 title / description / action', () => {
    render(
      <EmptyState
        testId="empty"
        title="暂无数据"
        description="去创建一个吧"
        action={<button type="button">新建</button>}
      />,
    )
    expect(screen.getByTestId('empty')).toBeInTheDocument()
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
    expect(screen.getByText('去创建一个吧')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新建' })).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('role=alert；点重试触发 onRetry', () => {
    const onRetry = vi.fn()
    render(<ErrorState message="加载失败" onRetry={onRetry} testId="err" />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalled()
  })
})
