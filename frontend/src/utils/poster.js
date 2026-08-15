/**
 * V3-6 分享海报（丰富化）：Canvas 2D 手绘 1080×1440（3:4），零依赖。
 *
 * 数据来自后端 GET /api/posters/data 一次装配（report + workout 摘要 + PR 明细 + 本周计数）。
 *
 * 布局（现代简约风：白底 / 圆角卡片 / 主色 indigo-600，系统默认字体栈）：
 * - 顶部品牌条（健身看板 + 日期）
 * - 有评分：评分环 + 标题同行（环左标题右，含"本周第 N 次训练"），其下三子分横向条形
 * - 指标行按 workout_kind 适配：strength=容量/时长/热量；cardio=距离/时长/热量（+平均心率）；
 *   mixed 两行排列；任何形态禁止 "-" 占位（缺失字段整格跳过）
 * - PR 明细行（🏆 动作名 重量×次数，多条取第一）
 * - 动作亮点区 top2-3（无评分版扩到 top4；纯有氧无亮点则隐藏）
 * - one_liner 点评卡（自动换行，≤2 行截断）
 * - 无评分：隐藏评分环与子分条，标题上移、指标放大，不留大片空白
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

/** 数字展示：60 → '60'；60.5 → '60.5'；非法 → null */
function fmtNum(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return n % 1 === 0 ? String(n) : String(Math.round(n * 100) / 100)
}

/** 距离：米 → 公里（保留两位去尾零）；≤0 或非法 → null */
function fmtDistance(meters) {
  const n = Number(meters)
  if (!Number.isFinite(n) || n <= 0) return null
  return `${fmtNum(Math.round(n / 10) / 100)} km`
}

function metric(label, value) {
  return value == null ? null : { label, value }
}

/** 指标行按 workout_kind 适配；缺失字段整格跳过（禁止 "-" 占位） */
function buildMetricRows(kind, workout) {
  const w = workout || {}
  const volume = fmtNum(w.volume_kg)
  const distance = fmtDistance(w.distance_m ?? w.cardio?.distance_m)
  const duration = w.duration_s != null ? formatDuration(w.duration_s) : null
  const calories = w.calories != null ? `${w.calories} kcal` : null
  const avgHr = w.avg_hr != null ? `${w.avg_hr} bpm` : null

  if (kind === 'cardio') {
    return [[
      metric('距离', distance),
      metric('时长', duration),
      metric('热量', calories),
      metric('平均心率', avgHr),
    ].filter(Boolean)]
  }
  if (kind === 'mixed') {
    return [
      [metric('总容量', volume != null ? `${volume} kg` : null),
        metric('距离', distance), metric('时长', duration)].filter(Boolean),
      [metric('热量', calories), metric('平均心率', avgHr)].filter(Boolean),
    ].filter((row) => row.length > 0)
  }
  // strength（默认）
  return [[
    metric('总容量', volume != null ? `${volume} kg` : null),
    metric('时长', duration),
    metric('热量', calories),
  ].filter(Boolean)]
}

/** 汇总后端 /api/posters/data 响应为海报绘制数据 */
export function buildPosterData(payload = {}) {
  const r = payload.report || {}
  const w = payload.workout || null
  const kind = w?.workout_kind || 'strength'
  const prs = Array.isArray(payload.prs) ? payload.prs : []
  return {
    date: w?.date || r.date || '',
    title: w?.title || r.workout_title || '训练记录',
    score: typeof r.score === 'number' && Number.isFinite(r.score) ? r.score : null,
    subscores: r.subscores && typeof r.subscores === 'object' ? r.subscores : null,
    oneLiner: truncateOneLiner(r.one_liner),
    kind,
    metricRows: buildMetricRows(kind, w),
    pr: prs.length > 0 ? prs[0] : null,
    highlights: Array.isArray(w?.highlights) ? w.highlights : [],
    weekCount: typeof payload.week_count === 'number' ? payload.week_count : null,
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
  ctx.fillStyle = COLOR_CARD
  ctx.fillRect(64, 140, POSTER_WIDTH - 128, 4)
}

/** 有评分：评分环（左）+ 标题（右）+ 本周计数，同一行区 */
function drawScoreHeader(ctx, data) {
  const cx = 250
  const cy = 350
  const radius = 120
  const lineWidth = 26
  const color = scoreTierColor(data.score)

  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = COLOR_RING_BG
  ctx.lineWidth = lineWidth
  ctx.lineCap = 'round'
  ctx.stroke()

  const start = -Math.PI / 2
  const end = start + (Math.max(0, Math.min(100, data.score)) / 100) * Math.PI * 2
  ctx.beginPath()
  ctx.arc(cx, cy, radius, start, end)
  ctx.strokeStyle = color
  ctx.stroke()

  ctx.fillStyle = color
  ctx.font = `bold 96px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(data.score), cx, cy - 4)
  ctx.font = `28px ${FONT_STACK}`
  ctx.fillText('分', cx + 70, cy + 38)

  // 标题（环右侧，左对齐）
  const title = String(data.title || '训练记录')
  ctx.fillStyle = COLOR_TEXT
  ctx.font = `bold 52px ${FONT_STACK}`
  ctx.textAlign = 'left'
  ctx.fillText(title.length > 10 ? `${title.slice(0, 9)}…` : title, 440, 330)
  if (data.weekCount != null) {
    ctx.fillStyle = COLOR_SUB
    ctx.font = `30px ${FONT_STACK}`
    ctx.fillText(`本周第 ${data.weekCount} 次训练`, 440, 395)
  }
}

/** 无评分：标题上移居中 + 本周计数 */
function drawPlainHeader(ctx, data) {
  const title = String(data.title || '训练记录')
  ctx.fillStyle = COLOR_TEXT
  ctx.font = `bold 64px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(title.length > 14 ? `${title.slice(0, 13)}…` : title, POSTER_WIDTH / 2, 320)
  if (data.weekCount != null) {
    ctx.fillStyle = COLOR_SUB
    ctx.font = `32px ${FONT_STACK}`
    ctx.fillText(`本周第 ${data.weekCount} 次训练`, POSTER_WIDTH / 2, 392)
  }
}

const SUBSCORE_LABELS = [
  ['completion', '完成度'],
  ['intensity', '强度'],
  ['recovery_fit', '恢复'],
]

/** 三子分横向条形（各 0-100），返回下一 y */
function drawSubscores(ctx, subscores, y, pitch = 50) {
  if (!subscores) return y
  SUBSCORE_LABELS.forEach(([key, label], i) => {
    const value = Math.max(0, Math.min(100, Number(subscores[key]) || 0))
    const rowY = y + i * pitch
    ctx.fillStyle = COLOR_TEXT
    ctx.font = `30px ${FONT_STACK}`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, 150, rowY)
    // 轨道 + 填充
    ctx.fillStyle = COLOR_RING_BG
    roundedRect(ctx, 330, rowY - 13, 540, 26, 13)
    ctx.fill()
    if (value > 0) {
      ctx.fillStyle = COLOR_INDIGO
      roundedRect(ctx, 330, rowY - 13, Math.max(26, (540 * value) / 100), 26, 13)
      ctx.fill()
    }
    ctx.fillStyle = COLOR_TEXT
    ctx.font = `bold 30px ${FONT_STACK}`
    ctx.textAlign = 'right'
    ctx.fillText(String(Math.round(value)), 950, rowY)
  })
  return y + SUBSCORE_LABELS.length * pitch
}

/** 指标行（1-2 行，每行 n 格均分），返回下一 y；large 为无评分放大版 */
function drawMetricRows(ctx, rows, y, { large = false } = {}) {
  const valid = (rows || []).filter((r) => r && r.length > 0)
  if (valid.length === 0) return y
  const valueSize = large ? 56 : 44
  const labelSize = large ? 32 : 28
  const pitch = large ? 120 : 96
  valid.forEach((row, ri) => {
    const rowY = y + ri * pitch
    row.forEach((item, i) => {
      const cx = (POSTER_WIDTH * (i + 0.5)) / row.length
      ctx.fillStyle = COLOR_TEXT
      ctx.font = `bold ${valueSize}px ${FONT_STACK}`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(item.value, cx, rowY)
      ctx.fillStyle = COLOR_SUB
      ctx.font = `${labelSize}px ${FONT_STACK}`
      ctx.fillText(item.label, cx, rowY + (large ? 64 : 54))
    })
  })
  return y + valid.length * pitch + 10
}

/** PR 明细行：🏆 动作名 重量×次数，返回下一 y */
function drawPrLine(ctx, pr, y) {
  const unit = pr.unit || 'kg'
  const reps = pr.reps ? `×${pr.reps}` : ''
  ctx.fillStyle = COLOR_PR
  ctx.font = `bold 36px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(`🏆 ${pr.movement} ${fmtNum(pr.weight)}${unit}${reps}`, POSTER_WIDTH / 2, y)
  return y + 60
}

/** 动作亮点区：圆角卡片 + top N（动作名 + 最佳组），返回下一 y */
function drawHighlights(ctx, highlights, y, limit) {
  const list = (highlights || []).slice(0, limit)
  if (list.length === 0) return y
  const cardH = 76 + list.length * 46
  ctx.fillStyle = COLOR_CARD
  roundedRect(ctx, 90, y, POSTER_WIDTH - 180, cardH, 24)
  ctx.fill()
  ctx.fillStyle = COLOR_INDIGO
  ctx.font = `bold 30px ${FONT_STACK}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('动作亮点', 130, y + 42)
  list.forEach((h, i) => {
    const unit = h.unit || 'kg'
    const text = `${h.name}  ${fmtNum(h.weight)}${unit}×${h.reps}`
    ctx.fillStyle = COLOR_TEXT
    ctx.font = `30px ${FONT_STACK}`
    ctx.fillText(text, 130, y + 84 + i * 46)
  })
  return y + cardH
}

function drawOneLiner(ctx, oneLiner, y) {
  const lines = wrapByChars(oneLiner)
  if (lines.length === 0) return
  const x = 90
  const w = POSTER_WIDTH - 180
  const h = lines.length > 1 ? 140 : 104
  ctx.fillStyle = COLOR_CARD
  roundedRect(ctx, x, y, w, h, 24)
  ctx.fill()
  ctx.fillStyle = COLOR_TEXT
  ctx.font = `34px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const startY = lines.length > 1 ? y + 48 : y + h / 2
  lines.forEach((line, i) => {
    ctx.fillText(line, POSTER_WIDTH / 2, startY + i * 48)
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
  ctx.fillStyle = COLOR_BG
  ctx.fillRect(0, 0, POSTER_WIDTH, POSTER_HEIGHT)
  drawBrandBar(ctx, data)

  if (data.score != null) {
    // 有评分：环 + 标题同行 → 子分条 → 指标 → PR → 亮点 top3 → 点评
    drawScoreHeader(ctx, data)
    // 内容少（纯有氧：无 PR 无亮点）时加大间距，避免下部空荡
    const sparse = (!data.highlights || data.highlights.length === 0) && !data.pr
    let y = drawSubscores(ctx, data.subscores, sparse ? 560 : 500, sparse ? 64 : 50)
    y = drawMetricRows(ctx, data.metricRows, y + (sparse ? 70 : 30))
    if (data.pr) y = drawPrLine(ctx, data.pr, y + 16)
    y = drawHighlights(ctx, data.highlights, y + 12, 3)
    drawOneLiner(ctx, data.oneLiner, y + (sparse ? 60 : 18))
  } else {
    // 无评分：标题上移、指标放大、亮点 top4，紧凑不留白
    drawPlainHeader(ctx, data)
    let y = drawMetricRows(ctx, data.metricRows, 500, { large: true })
    if (data.pr) y = drawPrLine(ctx, data.pr, y + 20)
    y = drawHighlights(ctx, data.highlights, y + 24, 4)
    drawOneLiner(ctx, data.oneLiner, y + 28)
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
