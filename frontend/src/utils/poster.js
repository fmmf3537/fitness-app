/**
 * V3-5 朋友圈分享海报：Canvas 2D 手绘 1080×1440（3:4），零依赖。
 *
 * 布局（现代简约风：白底 / 圆角卡片 / 主色 indigo-600，系统默认字体栈）：
 * - 顶部品牌条（健身看板 + 日期）
 * - 中部大号评分环（0-100，圆环进度 + 分数，配色按 V3-4 分档）；
 *   无 score 的旧报告降级为无评分布局（大标题居中，不画环）
 * - 训练标题 + 关键指标行（总容量/时长/热量，有 PR 加 PR 角标）
 * - one_liner 口语点评（最长 40 字，两行以内自动换行）
 * - 底部「由 健身看板 生成」水印条
 */
import { formatDuration } from './status'

export const POSTER_WIDTH = 1080
export const POSTER_HEIGHT = 1440

const COLOR_INDIGO = '#4f46e5' // indigo-600 主色
const COLOR_BG = '#ffffff'
const COLOR_TEXT = '#111827' // gray-900
const COLOR_SUB = '#6b7280' // gray-500
const COLOR_WATERMARK = '#9ca3af' // gray-400
const COLOR_RING_BG = '#e5e7eb' // gray-200
const COLOR_CARD = '#eef2ff' // indigo-50
const COLOR_PR = '#d97706' // amber-600

const FONT_STACK =
  '-apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'

const MAX_ONE_LINER = 40
const ONE_LINER_LINE = 20

/** V3-4 分档配色：≥90 绿 / 75-89 indigo / 60-74 黄 / <60 红；无评分用主色 */
export function scoreTierColor(score) {
  if (score == null) return COLOR_INDIGO
  if (score >= 90) return '#16a34a'
  if (score >= 75) return '#4f46e5'
  if (score >= 60) return '#ca8a04'
  return '#dc2626'
}

/** one_liner 兜底截断：最长 40 字，超出以 … 收尾 */
export function truncateOneLiner(text, max = MAX_ONE_LINER) {
  if (!text) return ''
  const t = String(text).trim()
  if (!t) return ''
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
}

/** 从报告正文粗判是否含 PR 事件（workout 无结构化 PR 字段，V3-5 假设） */
export function extractPrFlag(contentMd) {
  if (!contentMd) return false
  return /(个人纪录|新纪录|\bPR\b)/i.test(String(contentMd))
}

/** 总容量：Σ weight*reps；done === false 的组不计，done 缺省视为完成 */
export function computeVolumeKg(movements) {
  let total = 0
  for (const mv of Array.isArray(movements) ? movements : []) {
    for (const s of Array.isArray(mv?.sets) ? mv.sets : []) {
      if (s?.done === false) continue
      const w = Number(s?.weight)
      const r = Number(s?.reps)
      if (Number.isFinite(w) && Number.isFinite(r)) total += w * r
    }
  }
  return Math.round(total)
}

/** 汇总 report + workout 为海报绘制数据 */
export function buildPosterData({ report, workout } = {}) {
  const r = report || {}
  const w = workout || {}
  return {
    date: w.date || r.date || '',
    title: w.title || r.workout_title || '训练记录',
    score: typeof r.score === 'number' && Number.isFinite(r.score) ? r.score : null,
    oneLiner: truncateOneLiner(r.one_liner),
    volumeKg: computeVolumeKg(w.movements),
    durationS: typeof w.duration_s === 'number' ? w.duration_s : null,
    calories: typeof w.calories === 'number' ? w.calories : null,
    pr: extractPrFlag(r.content_md),
  }
}

/** 圆角矩形路径（兼容无 ctx.roundRect 的环境） */
function roundedRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.arcTo(x + w, y, x + w, y + r, r)
  ctx.lineTo(x + w, y + h - r)
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r)
  ctx.lineTo(x + r, y + h)
  ctx.arcTo(x, y + h, x, y + h - r, r)
  ctx.lineTo(x, y + r)
  ctx.arcTo(x, y, x + r, y, r)
  ctx.closePath()
}

/** 按字符数换行：每行 ≤ lineChars，最多两行 */
function wrapByChars(text, lineChars = ONE_LINER_LINE) {
  const t = String(text || '')
  if (!t) return []
  const lines = []
  for (let i = 0; i < t.length && lines.length < 2; i += lineChars) {
    lines.push(t.slice(i, i + lineChars))
  }
  return lines
}

function drawBrandBar(ctx, data) {
  ctx.fillStyle = COLOR_INDIGO
  ctx.font = `bold 42px ${FONT_STACK}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('健身看板', 64, 96)
  if (data.date) {
    ctx.fillStyle = COLOR_SUB
    ctx.font = `32px ${FONT_STACK}`
    ctx.textAlign = 'right'
    ctx.fillText(data.date, POSTER_WIDTH - 64, 96)
  }
  // 品牌条下分隔线
  ctx.fillStyle = COLOR_CARD
  ctx.fillRect(64, 140, POSTER_WIDTH - 128, 4)
}

function drawScoreRing(ctx, data) {
  const cx = POSTER_WIDTH / 2
  const cy = 470
  const radius = 190
  const lineWidth = 34
  const color = scoreTierColor(data.score)

  // 底环
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = COLOR_RING_BG
  ctx.lineWidth = lineWidth
  ctx.lineCap = 'round'
  ctx.stroke()

  // 进度环（从 12 点方向起，按 score/100 比例）
  const start = -Math.PI / 2
  const end = start + (Math.max(0, Math.min(100, data.score)) / 100) * Math.PI * 2
  ctx.beginPath()
  ctx.arc(cx, cy, radius, start, end)
  ctx.strokeStyle = color
  ctx.stroke()

  // 分数
  ctx.fillStyle = color
  ctx.font = `bold 150px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(data.score), cx, cy - 10)
  ctx.font = `36px ${FONT_STACK}`
  ctx.fillText('分', cx + 105, cy + 55)
  ctx.fillStyle = COLOR_SUB
  ctx.font = `34px ${FONT_STACK}`
  ctx.fillText('综合评分', cx, cy + radius + 70)

  // PR 角标（环右上）
  if (data.pr) drawPrBadge(ctx, cx + radius - 30, cy - radius - 10)
}

function drawPrBadge(ctx, x, y) {
  ctx.fillStyle = COLOR_PR
  roundedRect(ctx, x, y, 96, 52, 26)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.font = `bold 30px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('PR', x + 48, y + 27)
}

function drawTitle(ctx, data, y) {
  ctx.fillStyle = COLOR_TEXT
  ctx.font = `bold 56px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const title = String(data.title || '训练记录')
  ctx.fillText(title.length > 14 ? `${title.slice(0, 13)}…` : title, POSTER_WIDTH / 2, y)
}

function drawMetrics(ctx, data, y) {
  const items = [
    { value: data.volumeKg > 0 ? `${data.volumeKg} kg` : '-', label: '总容量' },
    { value: formatDuration(data.durationS), label: '时长' },
    { value: data.calories != null ? `${data.calories} kcal` : '-', label: '热量' },
  ]
  const centers = [POSTER_WIDTH / 6, POSTER_WIDTH / 2, (POSTER_WIDTH * 5) / 6]
  ctx.textAlign = 'center'
  items.forEach((item, i) => {
    ctx.fillStyle = COLOR_TEXT
    ctx.font = `bold 44px ${FONT_STACK}`
    ctx.textBaseline = 'middle'
    ctx.fillText(item.value, centers[i], y)
    ctx.fillStyle = COLOR_SUB
    ctx.font = `28px ${FONT_STACK}`
    ctx.fillText(item.label, centers[i], y + 56)
  })
}

function drawOneLiner(ctx, oneLiner, y) {
  const lines = wrapByChars(oneLiner)
  if (lines.length === 0) return
  const x = 90
  const w = POSTER_WIDTH - 180
  const h = lines.length > 1 ? 168 : 112
  ctx.fillStyle = COLOR_CARD
  roundedRect(ctx, x, y, w, h, 24)
  ctx.fill()
  ctx.fillStyle = COLOR_TEXT
  ctx.font = `34px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const startY = lines.length > 1 ? y + 56 : y + h / 2
  lines.forEach((line, i) => {
    ctx.fillText(line, POSTER_WIDTH / 2, startY + i * 56)
  })
}

function drawWatermark(ctx) {
  ctx.fillStyle = COLOR_CARD
  ctx.fillRect(0, POSTER_HEIGHT - 96, POSTER_WIDTH, 96)
  ctx.fillStyle = COLOR_WATERMARK
  ctx.font = `28px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('由 健身看板 生成', POSTER_WIDTH / 2, POSTER_HEIGHT - 48)
}

/** 在 1080×1440 的 2D context 上绘制海报 */
export function drawPoster(ctx, data) {
  // 白底
  ctx.fillStyle = COLOR_BG
  ctx.fillRect(0, 0, POSTER_WIDTH, POSTER_HEIGHT)

  drawBrandBar(ctx, data)

  if (data.score != null) {
    drawScoreRing(ctx, data)
    drawTitle(ctx, data, 830)
    drawMetrics(ctx, data, 950)
    drawOneLiner(ctx, data.oneLiner, 1080)
  } else {
    // 无评分降级布局：大标题居中 + PR 角标
    drawTitle(ctx, data, 430)
    ctx.font = `bold 56px ${FONT_STACK}`
    if (data.pr) drawPrBadge(ctx, POSTER_WIDTH / 2 + 220, 400)
    drawMetrics(ctx, data, 620)
    drawOneLiner(ctx, data.oneLiner, 800)
  }

  drawWatermark(ctx)
}

/** 创建画布并绘制，返回 canvas 元素（可注入 doc 便于测试） */
export function renderPosterCanvas(data, doc = document) {
  const canvas = doc.createElement('canvas')
  canvas.width = POSTER_WIDTH
  canvas.height = POSTER_HEIGHT
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('当前环境不支持 Canvas 2D')
  drawPoster(ctx, data)
  return canvas
}

/** 一步到位：渲染并导出 PNG dataURL */
export function renderPosterDataUrl(data) {
  return renderPosterCanvas(data).toDataURL('image/png')
}
