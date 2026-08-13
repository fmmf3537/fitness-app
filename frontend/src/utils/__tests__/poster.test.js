import { describe, expect, it, vi } from 'vitest'
import {
  POSTER_WIDTH,
  POSTER_HEIGHT,
  scoreTierColor,
  truncateOneLiner,
  extractPrFlag,
  computeVolumeKg,
  buildPosterData,
  drawPoster,
  renderPosterCanvas,
} from '../poster'

/** 记录调用的 mock 2D context（jsdom 无真实 canvas 实现） */
function createMockCtx() {
  const fillStyleHistory = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    font: '',
    textAlign: '',
    textBaseline: '',
    lineWidth: 1,
    lineCap: '',
    // 每次写文本时记录当时的 fillStyle，便于断言颜色分档
    fillText: vi.fn(() => fillStyleHistory.push(ctx.fillStyle)),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arcTo: vi.fn(),
    closePath: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    measureText: vi.fn((t) => ({ width: String(t).length * 30 })),
    __fillStyleHistory: fillStyleHistory,
  }
  return ctx
}

/** ctx.fillText 的全部文本（按调用顺序） */
function texts(ctx) {
  return ctx.fillText.mock.calls.map((c) => c[0])
}

describe('scoreTierColor（V3-4 分档）', () => {
  it('≥90 绿 / 75-89 indigo / 60-74 黄 / <60 红', () => {
    expect(scoreTierColor(100)).toBe('#16a34a')
    expect(scoreTierColor(90)).toBe('#16a34a')
    expect(scoreTierColor(89)).toBe('#4f46e5')
    expect(scoreTierColor(75)).toBe('#4f46e5')
    expect(scoreTierColor(74)).toBe('#ca8a04')
    expect(scoreTierColor(60)).toBe('#ca8a04')
    expect(scoreTierColor(59)).toBe('#dc2626')
    expect(scoreTierColor(0)).toBe('#dc2626')
  })

  it('无评分时用主色 indigo', () => {
    expect(scoreTierColor(null)).toBe('#4f46e5')
    expect(scoreTierColor(undefined)).toBe('#4f46e5')
  })
})

describe('truncateOneLiner', () => {
  it('不超长原样返回', () => {
    expect(truncateOneLiner('今天状态不错')).toBe('今天状态不错')
  })

  it('超过 40 字截断为 39 字 + …', () => {
    const long = '一'.repeat(50)
    const out = truncateOneLiner(long)
    expect(out).toHaveLength(40)
    expect(out.endsWith('…')).toBe(true)
  })

  it('空输入返回空串', () => {
    expect(truncateOneLiner(null)).toBe('')
    expect(truncateOneLiner(undefined)).toBe('')
    expect(truncateOneLiner('   ')).toBe('')
  })
})

describe('extractPrFlag', () => {
  it('内容含 PR / 个人纪录 / 新纪录 判定为有 PR', () => {
    expect(extractPrFlag('卧推刷新 PR 至 100kg')).toBe(true)
    expect(extractPrFlag('突破个人纪录')).toBe(true)
    expect(extractPrFlag('创了新纪录')).toBe(true)
  })

  it('普通内容 / 空内容为无 PR', () => {
    expect(extractPrFlag('本次训练完成度一般。')).toBe(false)
    expect(extractPrFlag(null)).toBe(false)
    expect(extractPrFlag('')).toBe(false)
  })
})

describe('computeVolumeKg', () => {
  it('按 weight*reps 汇总，跳过 done=false 的组', () => {
    const movements = [
      { name: '卧推', sets: [
        { weight: 80, reps: 10, done: true },
        { weight: 80, reps: 8, done: true },
        { weight: 100, reps: 5, done: false },
      ] },
      { name: '飞鸟', sets: [{ weight: 20, reps: 12, done: true }] },
    ]
    expect(computeVolumeKg(movements)).toBe(80 * 10 + 80 * 8 + 20 * 12)
  })

  it('done 缺省视为完成；空输入返回 0', () => {
    expect(computeVolumeKg([{ name: '深蹲', sets: [{ weight: 100, reps: 5 }] }])).toBe(500)
    expect(computeVolumeKg([])).toBe(0)
    expect(computeVolumeKg(null)).toBe(0)
    expect(computeVolumeKg([{ name: '空', sets: null }])).toBe(0)
  })
})

describe('buildPosterData', () => {
  const report = {
    score: 88,
    one_liner: '今天卧推状态爆棚，继续保持！',
    content_md: '卧推刷新 PR。',
    workout_title: '胸部训练',
    date: '2026-08-03',
  }
  const workout = {
    title: '胸部训练 · 晚',
    date: '2026-08-12',
    duration_s: 3600,
    calories: 420,
    movements: [{ name: '卧推', sets: [{ weight: 80, reps: 10, done: true }] }],
  }

  it('汇总 report + workout 为海报数据', () => {
    const data = buildPosterData({ report, workout })
    expect(data).toEqual({
      date: '2026-08-12',
      title: '胸部训练 · 晚',
      score: 88,
      oneLiner: '今天卧推状态爆棚，继续保持！',
      volumeKg: 800,
      durationS: 3600,
      calories: 420,
      pr: true,
    })
  })

  it('workout 缺失字段时回退到 report 字段', () => {
    const data = buildPosterData({ report, workout: null })
    expect(data.title).toBe('胸部训练')
    expect(data.date).toBe('2026-08-03')
    expect(data.volumeKg).toBe(0)
    expect(data.durationS).toBeNull()
    expect(data.calories).toBeNull()
  })

  it('无评分旧报告 score 为 null、oneLiner 为空串', () => {
    const data = buildPosterData({
      report: { score: null, one_liner: null, content_md: '无亮点', workout_title: '腿部' },
      workout: null,
    })
    expect(data.score).toBeNull()
    expect(data.oneLiner).toBe('')
    expect(data.pr).toBe(false)
  })
})

describe('drawPoster', () => {
  const base = {
    date: '2026-08-12',
    title: '胸部训练',
    score: 88,
    oneLiner: '今天卧推状态爆棚！',
    volumeKg: 5200,
    durationS: 3600,
    calories: 420,
    pr: false,
  }

  it('有评分：画分数文本、评分环弧度按分数比例、标题、指标、水印', () => {
    const ctx = createMockCtx()
    drawPoster(ctx, base)

    const t = texts(ctx)
    expect(t).toContain('88')
    expect(t).toContain('综合评分')
    expect(t).toContain('健身看板')
    expect(t).toContain('2026-08-12')
    expect(t).toContain('胸部训练')
    expect(t).toContain('5200 kg')
    expect(t).toContain('1 小时')
    expect(t).toContain('420 kcal')
    expect(t.some((x) => x.includes('由 健身看板 生成'))).toBe(true)
    expect(t.some((x) => x.includes('今天卧推状态爆棚！'))).toBe(true)

    // 评分环：进度弧 endAngle = -PI/2 + score/100 * 2PI
    const arcs = ctx.arc.mock.calls
    const progress = arcs.find((c) => Math.abs(c[4] - (-Math.PI / 2 + (88 / 100) * Math.PI * 2)) < 1e-9)
    expect(progress).toBeTruthy()
  })

  it('评分环颜色按分档（88 → indigo-600）', () => {
    const ctx = createMockCtx()
    drawPoster(ctx, base)
    // 分数文本绘制时 fillStyle 应为分档色
    const idx = ctx.fillText.mock.calls.findIndex((c) => c[0] === '88')
    expect(idx).toBeGreaterThanOrEqual(0)
    expect(ctx.__fillStyleHistory[idx]).toBe('#4f46e5')
  })

  it('无评分：降级布局，不画评分环与“综合评分”', () => {
    const ctx = createMockCtx()
    drawPoster(ctx, { ...base, score: null })
    const t = texts(ctx)
    expect(t).not.toContain('综合评分')
    expect(t).toContain('胸部训练')
    expect(t.some((x) => x.includes('由 健身看板 生成'))).toBe(true)
    // 无进度弧（只有装饰弧也不应存在）
    expect(ctx.arc).not.toHaveBeenCalled()
  })

  it('有 PR：绘制 PR 角标；无 PR 不绘制', () => {
    const ctxPr = createMockCtx()
    drawPoster(ctxPr, { ...base, pr: true })
    expect(texts(ctxPr)).toContain('PR')

    const ctxNo = createMockCtx()
    drawPoster(ctxNo, base)
    expect(texts(ctxNo)).not.toContain('PR')
  })

  it('长 one_liner 截断并自动换行（每行 ≤20 字）', () => {
    const ctx = createMockCtx()
    const long = '这'.repeat(45)
    drawPoster(ctx, { ...base, oneLiner: truncateOneLiner(long) })
    const lines = texts(ctx).filter((x) => x.includes('这'))
    expect(lines.length).toBe(2)
    expect(lines[0]).toHaveLength(20)
    expect(lines.join('')).toContain('…')
  })

  it('缺指标时显示占位符而不报错', () => {
    const ctx = createMockCtx()
    expect(() =>
      drawPoster(ctx, { date: '2026-08-12', title: '腿部', score: null, oneLiner: '', volumeKg: 0, durationS: null, calories: null, pr: false }),
    ).not.toThrow()
    const t = texts(ctx)
    expect(t.filter((x) => x === '-').length).toBeGreaterThanOrEqual(2)
  })
})

describe('renderPosterCanvas', () => {
  it('创建 1080×1440 画布并调用绘制', () => {
    const ctx = createMockCtx()
    const canvas = { width: 0, height: 0, getContext: vi.fn(() => ctx) }
    const doc = { createElement: vi.fn(() => canvas) }
    const out = renderPosterCanvas({ date: 'd', title: 't', score: 90, oneLiner: '', volumeKg: 0, durationS: null, calories: null, pr: false }, doc)
    expect(out).toBe(canvas)
    expect(canvas.width).toBe(POSTER_WIDTH)
    expect(canvas.height).toBe(POSTER_HEIGHT)
    expect(ctx.fillText).toHaveBeenCalled()
  })

  it('无法获取 2D context 时抛出明确错误', () => {
    const doc = { createElement: vi.fn(() => ({ getContext: () => null })) }
    expect(() => renderPosterCanvas({ title: 't' }, doc)).toThrow('Canvas')
  })
})
