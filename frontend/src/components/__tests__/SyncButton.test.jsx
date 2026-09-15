import { act, fireEvent, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SyncButton from '../SyncButton'
import SyncTaskProvider from '../SyncTaskProvider'
import { ToastProvider } from '../ui/Toast'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({ api: vi.fn(), getToken: () => localStorage.getItem('fh_token') }))
const IDLE = { running: false, status: null, date: null }
const RUNNING = { running: true, status: 'running', date: '2026-08-09', started_at: '2026-08-10T08:00:00' }
const SUCCESS = { ...RUNNING, running: false, status: 'success', finished_at: '2026-08-10T08:01:00', result: { detail: { workouts: 2, candidates: 1 } } }
const FAILED = { ...SUCCESS, status: 'failed', error: 'garmin 429 too many requests' }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function Wrapper({ children }) { return <ToastProvider><SyncTaskProvider>{children}</SyncTaskProvider></ToastProvider> }
async function mount(children = <SyncButton />) {
  let result
  await act(async () => { result = render(<Wrapper>{children}</Wrapper>) })
  return result
}
async function advance(ms = 3000) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
async function click() { await act(async () => { fireEvent.click(screen.getAllByRole('button', { name: '同步今日' })[0]) }) }
const posts = () => api.mock.calls.filter(([, options]) => options?.method === 'POST')
const reads = () => api.mock.calls.filter(([url]) => url === '/api/sync/status')

describe('共享同步任务', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-10T12:00:00+08:00'))
    localStorage.setItem('fh_token', 'test-token')
    api.mockReset()
  })
  afterEach(() => { vi.useRealTimers() })

  it('进入先查询；两个入口共享一次请求，快速重复点击只发一个 POST', async () => {
    const post = deferred()
    api.mockResolvedValueOnce(IDLE).mockReturnValueOnce(post.promise).mockResolvedValue(RUNNING)
    await mount(<><SyncButton /><SyncButton /></>)
    expect(reads()).toHaveLength(1)
    await click(); await click()
    expect(posts()).toHaveLength(1)
    expect(posts()[0][0]).toBe('/api/sync/2026-08-10')
    await act(async () => post.resolve({ status: 'started' }))
    expect(screen.getAllByText(/2026-08-09 同步中/)).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: '同步今日' })[0]).toBeDisabled()
  })

  it('恢复已运行任务，不发 POST；结束后只通知和刷新一次', async () => {
    const onSynced = vi.fn()
    api.mockResolvedValueOnce(RUNNING).mockResolvedValue(SUCCESS)
    await mount(<SyncButton onSynced={onSynced} />)
    await advance()
    expect(posts()).toHaveLength(0)
    expect(onSynced).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('toast-container')).toHaveTextContent('本次匹配产生候选 1 条')
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(onSynced).toHaveBeenCalledTimes(1)
    expect(reads()).toHaveLength(3)
    await advance()
    expect(reads()).toHaveLength(3)
  })

  it('离开按钮所在页面继续轮询，返回展示结果，不重新启动任务', async () => {
    api.mockResolvedValueOnce(RUNNING).mockResolvedValue(SUCCESS)
    const view = await mount()
    view.rerender(<Wrapper><p>另一个页面</p></Wrapper>)
    await advance()
    view.rerender(<Wrapper><SyncButton /></Wrapper>)
    expect(screen.getByText(/最近一次任务/)).toHaveTextContent('数据同步完成')
    expect(posts()).toHaveLength(0)
    expect(reads()).toHaveLength(2)
  })

  it('重新挂载模拟刷新，从服务端恢复任务；旧请求被中止', async () => {
    api.mockResolvedValue(RUNNING)
    const first = await mount()
    const signal = reads()[0][1].signal
    first.unmount()
    expect(signal.aborted).toBe(true)
    await mount()
    expect(reads()).toHaveLength(2)
    expect(posts()).toHaveLength(0)
  })

  it('409 后立即查询现有任务并持续跟踪', async () => {
    api.mockResolvedValueOnce(IDLE).mockRejectedValueOnce({ status: 409 }).mockResolvedValueOnce(RUNNING).mockResolvedValue(SUCCESS)
    await mount(); await click()
    expect(screen.getByText(/2026-08-09 同步中/)).toBeInTheDocument()
    await advance()
    expect(screen.getByTestId('toast-container')).toHaveTextContent('数据同步完成')
    expect(posts()).toHaveLength(1)
  })

  it('断网仅标记状态未知，保留任务且禁止重复提交，恢复后继续跟踪', async () => {
    api.mockResolvedValueOnce(RUNNING).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(SUCCESS)
    await mount(); await advance()
    expect(screen.getByRole('alert')).toHaveTextContent('暂时无法确认同步状态')
    expect(screen.queryByText(/同步失败/)).not.toBeInTheDocument()
    await click(); expect(posts()).toHaveLength(0)
    await advance()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText(/最近一次任务/)).toHaveTextContent('数据同步完成')
  })

  it('初次查询失败可以手动重新查询，不触发同步', async () => {
    api.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(IDLE)
    await mount()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '重新查询状态' })) })
    expect(screen.getByText('服务端暂无最近任务记录')).toBeInTheDocument()
    expect(posts()).toHaveLength(0)
  })

  it('任务失败与限频提示来自服务端，同时通知页面刷新部分导入数据', async () => {
    const onSynced = vi.fn()
    api.mockResolvedValueOnce(RUNNING).mockResolvedValue(FAILED)
    await mount(<SyncButton onSynced={onSynced} />); await advance()
    expect(screen.getByRole('alert')).toHaveTextContent('数据来源接口限频')
    expect(onSynced).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '同步今日' })).not.toBeDisabled()
  })

  it('AI 失败不标记为全部完成，也不显示成功图标', async () => {
    api.mockResolvedValueOnce(RUNNING).mockResolvedValue({ ...SUCCESS, result: { detail: { ai_reviews_failed: true } } })
    await mount(); await advance()
    expect(screen.getByTestId('toast-container')).toHaveTextContent('AI 点评或下次建议未完成')
    expect(screen.getByTestId('toast-container').querySelector('svg')).toBeNull()
    expect(screen.getByTestId('toast-container')).not.toHaveTextContent('训练 0 条')
  })

  it('初始历史结果不重复弹 toast；时间原样展示，不伪造最近成功时间', async () => {
    api.mockResolvedValue(SUCCESS)
    await mount()
    expect(screen.getByTestId('toast-container')).toBeEmptyDOMElement()
    expect(screen.getByText(/结束时间/)).toHaveTextContent('2026-08-10 08:01:00')
    expect(screen.queryByText(/最近成功/)).not.toBeInTheDocument()
  })

  it('focus 与 visibilitychange 同时触发时合并请求，避免乱序', async () => {
    const pending = deferred()
    api.mockResolvedValueOnce(IDLE).mockReturnValueOnce(pending.promise)
    await mount()
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(reads()).toHaveLength(2)
    await act(async () => pending.resolve(RUNNING))
    expect(screen.getByRole('button', { name: '同步今日' })).toBeDisabled()
  })

  it('退出后旧响应不更新新会话，且停止计时轮询', async () => {
    const pending = deferred()
    api.mockReturnValueOnce(pending.promise).mockResolvedValue(IDLE)
    const view = await mount()
    view.unmount()
    localStorage.setItem('fh_token', 'new-token')
    await mount()
    await act(async () => pending.resolve(RUNNING))
    await advance()
    expect(screen.getByText('服务端暂无最近任务记录')).toBeInTheDocument()
    expect(reads()).toHaveLength(2)
  })

  it('服务端运行中任务突然丢失时不伪造结束结果', async () => {
    api.mockResolvedValueOnce(RUNNING).mockResolvedValue(IDLE)
    await mount(); await advance()
    expect(screen.getByRole('alert')).toHaveTextContent('暂时无法确认同步状态')
    expect(screen.getByRole('button', { name: '同步今日' })).toBeDisabled()
  })

  it('POST 响应丢失后查询服务端，不自动重发 POST', async () => {
    api.mockResolvedValueOnce(IDLE).mockRejectedValueOnce(new Error('network')).mockResolvedValue(RUNNING)
    await mount(); await click()
    expect(posts()).toHaveLength(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText(/2026-08-09 同步中/)).toBeInTheDocument()
  })

  it('POST 响应丢失且状态仍是旧任务时保持未知并禁止再次提交', async () => {
    api.mockResolvedValueOnce(SUCCESS).mockRejectedValueOnce(new Error('network')).mockResolvedValue(SUCCESS)
    await mount(); await click()
    expect(posts()).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('暂时无法确认同步状态')
    await click()
    expect(posts()).toHaveLength(1)
  })

  it('StrictMode 清理旧请求；不接受已卸载 effect 的响应', async () => {
    const pending = deferred()
    api.mockReturnValueOnce(pending.promise).mockResolvedValue(IDLE)
    await act(async () => { render(<StrictMode><Wrapper><SyncButton /></Wrapper></StrictMode>) })
    await act(async () => pending.resolve(RUNNING))
    expect(screen.getByText('服务端暂无最近任务记录')).toBeInTheDocument()
    expect(reads()[0][1].signal.aborted).toBe(true)
  })
})
