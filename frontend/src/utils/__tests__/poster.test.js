/**
 * V3-6 海报内容丰富化测试：六种数据形态 + 布局重排断言。
 * mock canvas 2D context，断言绘制调用序列关键参数。
 */
import { describe, it, expect, vi } from 'vitest'
import {
  POSTER_WIDTH,
  POSTER_HEIGHT,
  scoreTierColor,
  truncateOneLiner,
  buildPosterData,
  drawPoster,
  renderPosterCanvas,
} from '../poster'

function createMockCtx() {
  const fillStyleHistory = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    font: '',
    textAlign: '',
    textBaseline: '',
    lineWidth: 0,
    lineCap: '',
    fillRect: vi.fn(),
    fillText: vi.fn(() => fillStyleHistory.push(ctx.fillStyle)),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arcTo: vi.fn(),
    arc: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    __fillStyleHistory: fillStyleHistory,
  }
  return ctx
}

function texts(ctx) {
  return ctx.fillText.mock.calls.map((c) => c[0])
}

/** 找某文本第一次绘制时的 y 坐标 */
function textY(ctx, text) {
  const call = ctx.fillText.mock.calls.find((c) => c[0] === text)
  return call ? call[2] : null
}

const SCORED_STRENGTH_PAYLOAD = {
  report: {
    id: 1,
    type: 'session_review',
    date: '2026-08-05',
    workout_title: '胸部训练',
    score: 88,
    one_liner: '今天状态火热，卧推破了个人纪录！',
    subscores: { completion: 90, intensity: 85, recovery_fit: 80 },
  },
  workout: {
    id: 10,
    date: '2026-08-05',
    title: '胸部训练',
    workout_kind: 'strength',
    duration_s: 4020,
    calories: 486,
    avg_hr: 118,
    max_hr: 152,
    distance_m: null,
    volume_kg: 2220,
    highlights: [
      { name: '杠铃卧推', weight: 60, unit: 'kg', reps: 10, volume_kg: 1120 },
      { name: '哑铃划船', weight: 30, unit: 'kg', reps: 12, volume_kg: 720 },
      { name: '坐姿推肩', weight: 20, unit: 'kg', reps: 10, volume_kg: 200 },
    ],
    cardio: null,
  },
  prs: [{ movement: '杠铃卧推', weight: 65, unit: 'kg', reps: 8 }],
  week_count: 3,
}

const CARDIO_PAYLOAD = {
  report: { ...SCORED_STRENGTH_PAYLOAD.report, workout_title: '晨跑', one_liner: '配速稳定，恢复不错。' },
  workout: {
    id: 11,
    date: '2026-08-05',
    title: '晨跑',
    workout_kind: 'cardio',
    duration_s: 2400,
    calories: 320,
    avg_hr: 145,
    max_hr: 168,
    distance_m: 5200.5,
    volume_kg: 0,
    highlights: [],
    cardio: { distance_m: 5200.5, avg_hr: 145, duration_s: 2400, calories: 320 },
  },
  prs: [],
  week_count: 1,
}

describe('scoreTierColor / truncateOneLiner', () => {
  it('按 V3-4 分档配色', () => {
    expect(scoreTierColor(95)).toBe('#16a34a')
    expect(scoreTierColor(88)).toBe('#4f46e5')
    expect(scoreTierColor(60)).toBe('#ca8a04')
    expect(scoreTierColor(30)).toBe('#dc2626')
    expect(scoreTierColor(null)).toBe('#4f46e5')
  })

  it('one_liner 超长截断', () => {
    expect(truncateOneLiner('短')).toBe('短')
    expect(truncateOneLiner('x'.repeat(41))).toHaveLength(40)
    expect(truncateOneLiner('x'.repeat(41)).endsWith('…')).toBe(true)
    expect(truncateOneLiner(null)).toBe('')
  })
})

describe('buildPosterData', () => {
  it('力量形态：指标行=容量/时长/热量，PR 取第一条，亮点透传', () => {
    const d = buildPosterData(SCORED_STRENGTH_PAYLOAD)
    expect(d.title).toBe('胸部训练')
    expect(d.date).toBe('2026-08-05')
    expect(d.score).toBe(88)
    expect(d.subscores).toEqual({ completion: 90, intensity: 85, recovery_fit: 80 })
    expect(d.kind).toBe('strength')
    expect(d.metricRows).toHaveLength(1)
    expect(d.metricRows[0].map((m) => m.label)).toEqual(['总容量', '时长', '热量'])
    expect(d.metricRows[0][0].value).toBe('2220 kg')
    expect(d.pr).toEqual({ movement: '杠铃卧推', weight: 65, unit: 'kg', reps: 8 })
    expect(d.highlights).toHaveLength(3)
    expect(d.weekCount).toBe(3)
  })

  it('有氧形态：指标行=距离/时长/热量/平均心率，无容量无占位符', () => {
    const d = buildPosterData(CARDIO_PAYLOAD)
    expect(d.kind).toBe('cardio')
    expect(d.metricRows).toHaveLength(1)
    const labels = d.metricRows[0].map((m) => m.label)
    expect(labels).toEqual(['距离', '时长', '热量', '平均心率'])
    expect(labels).not.toContain('总容量')
    expect(d.metricRows[0][0].value).toBe('5.2 km')
    expect(d.metricRows[0][3].value).toBe('145 bpm')
    expect(d.highlights).toHaveLength(0)
    expect(d.pr).toBeNull()
  })

  it('混合形态：两行指标，第一行容量/距离/时长，第二行热量/平均心率', () => {
    const payload = {
      ...SCORED_STRENGTH_PAYLOAD,
      workout: {
        ...SCORED_STRENGTH_PAYLOAD.workout,
        workout_kind: 'mixed',
        distance_m: 3000,
        cardio: { distance_m: 3000, avg_hr: 138, duration_s: 4020, calories: 486 },
        avg_hr: 138,
      },
    }
    const d = buildPosterData(payload)
    expect(d.kind).toBe('mixed')
    expect(d.metricRows).toHaveLength(2)
    expect(d.metricRows[0].map((m) => m.label)).toEqual(['总容量', '距离', '时长'])
    expect(d.metricRows[1].map((m) => m.label)).toEqual(['热量', '平均心率'])
  })

  it('缺失字段一律跳过而非 "-" 占位', () => {
    const payload = {
      report: { id: 2, date: '2026-08-05', workout_title: '徒手', score: null, one_liner: null, subscores: null },
      workout: {
        id: 12, date: '2026-08-05', title: '徒手', workout_kind: 'strength',
        duration_s: null, calories: null, avg_hr: null, max_hr: null,
        distance_m: null, volume_kg: 0, highlights: [], cardio: null,
      },
      prs: [],
      week_count: null,
    }
    const d = buildPosterData(payload)
    const all = d.metricRows.flat()
    expect(all.every((m) => m.value !== '-')).toBe(true)
    expect(all.map((m) => m.label)).toEqual(['总容量'])
    expect(d.score).toBeNull()
    expect(d.oneLiner).toBe('')
  })

  it('无 workout 关联：指标/亮点/PR 全空，报告字段仍可用', () => {
    const payload = {
      report: { id: 3, date: '2026-08-03', workout_title: null, score: 80, one_liner: '加油', subscores: null },
      workout: null,
      prs: [],
      week_count: null,
    }
    const d = buildPosterData(payload)
    expect(d.title).toBe('训练记录')
    expect(d.metricRows.flat()).toHaveLength(0)
    expect(d.highlights).toHaveLength(0)
    expect(d.pr).toBeNull()
    expect(d.weekCount).toBeNull()
  })
})

describe('drawPoster 六种形态', () => {
  it('完整力量：评分环+子分条+容量指标+PR 明细+亮点 top3+点评', () => {
    const ctx = createMockCtx()
    drawPoster(ctx, buildPosterData(SCORED_STRENGTH_PAYLOAD))
    const t = texts(ctx)
    // 评分环
    expect(ctx.arc).toHaveBeenCalled()
    expect(t).toContain('88')
    // 子分条
    expect(t).toContain('完成度')
    expect(t).toContain('强度')
    expect(t).toContain('恢复')
    expect(t).toContain('90')
    expect(t).toContain('85')
    expect(t).toContain('80')
    // 指标行
    expect(t).toContain('总容量')
    expect(t).toContain('2220 kg')
    expect(t).toContain('时长')
    expect(t).toContain('热量')
    expect(t).toContain('486 kcal')
    // PR 明细行
    expect(t.some((s) => s.includes('🏆') && s.includes('杠铃卧推') && s.includes('65kg×8'))).toBe(true)
    // 亮点区
    expect(t).toContain('动作亮点')
    expect(t.some((s) => s.includes('杠铃卧推') && s.includes('60kg×10'))).toBe(true)
    expect(t.some((s) => s.includes('哑铃划船'))).toBe(true)
    expect(t.some((s) => s.includes('坐姿推肩'))).toBe(true)
    // 本周计数
    expect(t.some((s) => s.includes('本周第 3 次训练'))).toBe(true)
    // 点评 + 水印
    expect(t.some((s) => s.includes('今天状态火热'))).toBe(true)
    expect(t).toContain('由 健身看板 生成')
    // 分数颜色分档
    const idx = ctx.fillText.mock.calls.findIndex((c) => c[0] === '88')
    expect(ctx.__fillStyleHistory[idx]).toBe('#4f46e5')
  })

  it('完整有氧：距离四栏指标、无 "-" 占位、隐藏亮点区', () => {
    const ctx = createMockCtx()
    drawPoster(ctx, buildPosterData(CARDIO_PAYLOAD))
    const t = texts(ctx)
    expect(t).toContain('距离')
    expect(t).toContain('5.2 km')
    expect(t).toContain('平均心率')
    expect(t).toContain('145 bpm')
    expect(t).not.toContain('总容量')
    expect(t).not.toContain('-')
    expect(t).not.toContain('动作亮点')
    expect(t.some((s) => s.includes('🏆'))).toBe(false)
    expect(t.some((s) => s.includes('本周第 1 次训练'))).toBe(true)
  })

  it('无评分：不画环与子分条，标题上移，亮点扩到 top4', () => {
    const payload = {
      ...SCORED_STRENGTH_PAYLOAD,
      report: { ...SCORED_STRENGTH_PAYLOAD.report, score: null, subscores: null },
      workout: {
        ...SCORED_STRENGTH_PAYLOAD.workout,
        highlights: [
          ...SCORED_STRENGTH_PAYLOAD.workout.highlights,
          { name: '绳索下压', weight: 15, unit: 'kg', reps: 12, volume_kg: 180 },
        ],
      },
    }
    const ctx = createMockCtx()
    const data = buildPosterData(payload)
    drawPoster(ctx, data)
    const t = texts(ctx)
    // 无评分环（arc 仅评分环使用）
    expect(ctx.arc).not.toHaveBeenCalled()
    expect(t).not.toContain('完成度')
    // 标题上移：无评分版标题 y 显著小于有评分版
    const scoredCtx = createMockCtx()
    drawPoster(scoredCtx, buildPosterData(SCORED_STRENGTH_PAYLOAD))
    expect(textY(ctx, '胸部训练')).toBeLessThan(textY(scoredCtx, '胸部训练'))
    // 亮点 top4 全部出现
    expect(t.some((s) => s.includes('绳索下压'))).toBe(true)
    // 无 "-" 占位
    expect(t).not.toContain('-')
    // 中部不空：指标行仍存在且位于上半区
    expect(t).toContain('总容量')
  })

  it('无 PR：不出现 🏆 行', () => {
    const payload = { ...SCORED_STRENGTH_PAYLOAD, prs: [] }
    const ctx = createMockCtx()
    drawPoster(ctx, buildPosterData(payload))
    expect(texts(ctx).some((s) => s.includes('🏆'))).toBe(false)
  })

  it('无亮点：力量但 highlights 为空时隐藏亮点区', () => {
    const payload = {
      ...SCORED_STRENGTH_PAYLOAD,
      workout: { ...SCORED_STRENGTH_PAYLOAD.workout, highlights: [] },
    }
    const ctx = createMockCtx()
    drawPoster(ctx, buildPosterData(payload))
    expect(texts(ctx)).not.toContain('动作亮点')
  })

  it('混合：两行指标排列且无 "-" 占位', () => {
    const payload = {
      ...SCORED_STRENGTH_PAYLOAD,
      workout: {
        ...SCORED_STRENGTH_PAYLOAD.workout,
        workout_kind: 'mixed',
        distance_m: 3000,
        avg_hr: 138,
        cardio: { distance_m: 3000, avg_hr: 138, duration_s: 4020, calories: 486 },
      },
    }
    const ctx = createMockCtx()
    const data = buildPosterData(payload)
    drawPoster(ctx, data)
    const t = texts(ctx)
    expect(t).toContain('总容量')
    expect(t).toContain('距离')
    expect(t).toContain('3 km')
    expect(t).toContain('平均心率')
    expect(t).not.toContain('-')
    // 两行：热量标签的 y 大于 时长标签的 y
    expect(textY(ctx, '热量')).toBeGreaterThan(textY(ctx, '时长'))
  })
})

describe('renderPosterCanvas', () => {
  it('创建 1080×1440 画布并绘制', () => {
    const ctx = createMockCtx()
    const canvas = { width: 0, height: 0, getContext: vi.fn(() => ctx) }
    const doc = { createElement: vi.fn(() => canvas) }
    const out = renderPosterCanvas(buildPosterData(SCORED_STRENGTH_PAYLOAD), doc)
    expect(out).toBe(canvas)
    expect(canvas.width).toBe(POSTER_WIDTH)
    expect(canvas.height).toBe(POSTER_HEIGHT)
    expect(canvas.getContext).toHaveBeenCalledWith('2d')
  })

  it('无法获取 2D context 时抛出明确错误', () => {
    const canvas = { width: 0, height: 0, getContext: vi.fn(() => null) }
    const doc = { createElement: vi.fn(() => canvas) }
    expect(() => renderPosterCanvas({}, doc)).toThrow('Canvas')
  })
})
