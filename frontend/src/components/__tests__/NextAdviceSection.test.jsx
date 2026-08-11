import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NextAdviceSection from '../NextAdviceSection'
import { parseNextAdvice } from '../../utils/nextAdvice'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const WORKOUT = {
  id: 10,
  date: '2026-08-03',
  title: '背部训练',
  xunji_raw: { localid: 111 },
  movements: [
    {
      name: '宽距高位下拉',
      sets: [{ weight: '50', unit: 'kg', reps: '10', done: true }],
    },
  ],
}

const PREVIEW_RESP = {
  datestr: '2026-08-03',
  localid: '111',
  diff: [
    { field: 'title', old: '背部训练', new: '背部训练', changed: false },
    { field: '动作1 宽距高位下拉 第1组 rpe', old: null, new: '8', changed: true },
  ],
  train: { datestr: '2026-08-03', localid: 111 },
}

/** 按 URL 分发 mock：报告 / 预览 / 确认。 */
function mockFetchFlow({ confirmResp = { status: 'written' } } = {}) {
  globalThis.fetch = vi.fn((url) => {
    if (url.startsWith('/api/writeback/preview')) {
      return Promise.resolve(mockResponse(PREVIEW_RESP))
    }
    if (url.startsWith('/api/writeback/confirm')) {
      return Promise.resolve(mockResponse(confirmResp))
    }
    return Promise.resolve(mockResponse({ reports: [REPORT] }))
  })
}

const ADVICE_JSON = {
  schema: 'next_advice_v1',
  next_plan_date: '2026-08-05',
  suggestions: [
    {
      movement: '杠铃划船',
      category: 'manual',
      original: { weight: 60, unit: 'kg', sets: 4, reps: 10 },
      suggested: { weight: 62.5, unit: 'kg', sets: 4, reps: 8 },
      reason: '上次 RPE 偏低，渐进超负荷',
    },
    {
      movement: '宽距高位下拉',
      category: 'auto_writable',
      original: { rpe: null },
      suggested: { rpe: 8 },
      reason: '补录本次训练 RPE',
    },
  ],
}

const CONTENT = `## 计划对照
下次训练建议加重。

\`\`\`json
${JSON.stringify(ADVICE_JSON)}
\`\`\``

const REPORT = {
  id: 2,
  type: 'next_advice',
  workout_id: 10,
  date: '2026-08-03',
  workout_title: '背部训练',
  model: 'deepseek-chat',
  prompt_tokens: 100,
  completion_tokens: 50,
  cost_estimate: 0.0003,
  content_md: CONTENT,
  created_at: '2026-08-03T23:10:00',
}

describe('parseNextAdvice', () => {
  it('拆分 Markdown 正文与结构化建议', () => {
    const { markdown, advice } = parseNextAdvice(CONTENT)
    expect(markdown).toContain('计划对照')
    expect(markdown).not.toContain('```json')
    expect(advice.schema).toBe('next_advice_v1')
    expect(advice.suggestions).toHaveLength(2)
  })

  it('无 JSON 块时 advice 为 null', () => {
    const { markdown, advice } = parseNextAdvice('## 只有正文')
    expect(markdown).toContain('只有正文')
    expect(advice).toBeNull()
  })

  it('JSON 块损坏时 advice 为 null 且保留正文', () => {
    const { markdown, advice } = parseNextAdvice('正文\n```json\n{bad}\n```')
    expect(advice).toBeNull()
    expect(markdown).toContain('正文')
  })
})

describe('NextAdviceSection', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [REPORT] })))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('按 workout 拉取 next_advice 报告', async () => {
    render(<NextAdviceSection workout={WORKOUT} />)
    expect(await screen.findByText('下次训练建议')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports?date=2026-08-03&type=next_advice',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('渲染两类建议区块', async () => {
    render(<NextAdviceSection workout={WORKOUT} />)
    expect(await screen.findByTestId('auto-writable-block')).toBeInTheDocument()
    expect(screen.getByTestId('manual-block')).toBeInTheDocument()
    // 可自动写回：宽距高位下拉
    const autoBlock = screen.getByTestId('auto-writable-block')
    expect(autoBlock.textContent).toContain('宽距高位下拉')
    expect(autoBlock.textContent).toContain('补录本次训练 RPE')
    // 需手动调整：杠铃划船 + 训记 App 操作指引
    const manualBlock = screen.getByTestId('manual-block')
    expect(manualBlock.textContent).toContain('杠铃划船')
    expect(manualBlock.textContent).toContain('渐进超负荷')
    expect(manualBlock.textContent).toContain('训记 App')
  })

  it('点击「生成写回预览」调用 preview 接口并渲染 diff 表格（变更高亮）', async () => {
    const user = userEvent.setup()
    mockFetchFlow()
    render(<NextAdviceSection workout={WORKOUT} />)
    const btn = await screen.findByRole('button', { name: '生成写回预览' })
    await user.click(btn)

    // preview 请求体：localid + 应用建议后的 changes
    const previewCall = globalThis.fetch.mock.calls.find(([url]) =>
      url.startsWith('/api/writeback/preview'),
    )
    expect(previewCall).toBeTruthy()
    const body = JSON.parse(previewCall[1].body)
    expect(body.datestr).toBe('2026-08-03')
    expect(body.localid).toBe(111)
    expect(body.changes.movements[0].sets[0].rpe).toBe('8')

    // diff 表格：字段/原值/新值三列
    const preview = await screen.findByTestId('writeback-preview-0')
    expect(preview.textContent).toContain('字段')
    expect(preview.textContent).toContain('原值')
    expect(preview.textContent).toContain('新值')
    const changedCell = await screen.findByText('动作1 宽距高位下拉 第1组 rpe')
    expect(changedCell.closest('tr').className).toContain('bg-amber')
    // 窄屏可横向滚动：diff 表外层包 overflow-x-auto 容器
    const diffTable = preview.querySelector('table')
    expect(diffTable.parentElement).toHaveClass('overflow-x-auto')
  })

  it('「确认写回」弹窗确认后调用 confirm 接口并显示成功', async () => {
    const user = userEvent.setup()
    mockFetchFlow()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<NextAdviceSection workout={WORKOUT} />)
    await user.click(await screen.findByRole('button', { name: '生成写回预览' }))
    await user.click(await screen.findByRole('button', { name: '确认写回' }))

    expect(window.confirm).toHaveBeenCalled()
    const confirmCall = globalThis.fetch.mock.calls.find(([url]) =>
      url.startsWith('/api/writeback/confirm'),
    )
    expect(confirmCall).toBeTruthy()
    expect(await screen.findByText(/写回成功/)).toBeInTheDocument()
  })

  it('弹窗取消时不发起真实写回', async () => {
    const user = userEvent.setup()
    mockFetchFlow()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<NextAdviceSection workout={WORKOUT} />)
    await user.click(await screen.findByRole('button', { name: '生成写回预览' }))
    await user.click(await screen.findByRole('button', { name: '确认写回' }))

    const confirmCall = globalThis.fetch.mock.calls.find(([url]) =>
      url.startsWith('/api/writeback/confirm'),
    )
    expect(confirmCall).toBeUndefined()
  })

  it('无报告时显示空状态', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ reports: [] })))
    render(<NextAdviceSection workout={WORKOUT} />)
    expect(await screen.findByText('暂无下次训练建议')).toBeInTheDocument()
  })

  it('报告属于其他 workout 时不展示', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ reports: [{ ...REPORT, workout_id: 999 }] })),
    )
    render(<NextAdviceSection workout={WORKOUT} />)
    expect(await screen.findByText('暂无下次训练建议')).toBeInTheDocument()
  })

  it('建议 JSON 缺失时仅渲染 Markdown 正文', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        mockResponse({ reports: [{ ...REPORT, content_md: '## 计划对照\n只有正文' }] }),
      ),
    )
    render(<NextAdviceSection workout={WORKOUT} />)
    expect(await screen.findByText('下次训练建议')).toBeInTheDocument()
    expect(screen.getByText(/计划对照/)).toBeInTheDocument()
    expect(screen.queryByTestId('auto-writable-block')).not.toBeInTheDocument()
  })
})
