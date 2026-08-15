/**
 * V3-6 海报效果预览页生成器（开发辅助，不进运行时包）：
 * 把 src/utils/poster.js（及其依赖 status.js）内联进独立 HTML，
 * 六种数据形态各生成一页，用无头浏览器打开截图即得效果图。
 *
 * 用法：node scripts/render-poster-demo.mjs [输出目录]
 * 产出：poster-demo-{strength,cardio,noscore,nopr,nohighlight,mixed}.html
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = process.argv[2] || here

function inline(rel) {
  return readFileSync(join(here, '..', rel), 'utf8')
    .replace(/^import .*$/gm, '') // 去掉跨文件 import（status.js 已内联）
    .replace(/^export default /gm, '')
    .replace(/^export /gm, '')
}

const statusJs = inline('src/utils/status.js')
const posterJs = inline('src/utils/poster.js')

const baseReport = {
  id: 1,
  type: 'session_review',
  date: '2026-08-15',
  workout_title: '胸部训练 · 推日',
  score: 88,
  one_liner: '卧推 65kg 破纪录，恢复良好，下次冲 67.5！',
  subscores: { completion: 90, intensity: 85, recovery_fit: 80 },
}
const strengthWorkout = {
  id: 10,
  date: '2026-08-15',
  title: '胸部训练 · 推日',
  workout_kind: 'strength',
  duration_s: 4020,
  calories: 486,
  avg_hr: 118,
  max_hr: 152,
  distance_m: null,
  volume_kg: 8240,
  highlights: [
    { name: '杠铃卧推', weight: 65, unit: 'kg', reps: 8, volume_kg: 3060 },
    { name: '哑铃上斜卧推', weight: 26, unit: 'kg', reps: 10, volume_kg: 2080 },
    { name: '坐姿推肩', weight: 22.5, unit: 'kg', reps: 10, volume_kg: 1350 },
    { name: '绳索下压', weight: 20, unit: 'kg', reps: 12, volume_kg: 960 },
  ],
  cardio: null,
}

const shapes = {
  // 1. 完整力量（评分 + 子分 + PR + 亮点 + 点评）
  strength: {
    report: baseReport,
    workout: strengthWorkout,
    prs: [{ movement: '杠铃卧推', weight: 65, unit: 'kg', reps: 8 }],
    week_count: 3,
  },
  // 2. 完整有氧（距离/时长/热量/心率四栏，无亮点区）
  cardio: {
    report: { ...baseReport, workout_title: '晨跑 5 公里', one_liner: '配速稳定，心率控制不错，恢复良好。' },
    workout: {
      id: 11, date: '2026-08-15', title: '晨跑 5 公里', workout_kind: 'cardio',
      duration_s: 2400, calories: 320, avg_hr: 145, max_hr: 168,
      distance_m: 5200, volume_kg: 0, highlights: [],
      cardio: { distance_m: 5200, avg_hr: 145, duration_s: 2400, calories: 320 },
    },
    prs: [],
    week_count: 1,
  },
  // 3. 无评分（标题上移、指标放大、亮点 top4）
  noscore: {
    report: { ...baseReport, score: null, subscores: null },
    workout: strengthWorkout,
    prs: [{ movement: '杠铃卧推', weight: 65, unit: 'kg', reps: 8 }],
    week_count: 3,
  },
  // 4. 无 PR
  nopr: {
    report: baseReport,
    workout: strengthWorkout,
    prs: [],
    week_count: 2,
  },
  // 5. 无亮点（自重/无有效组）
  nohighlight: {
    report: { ...baseReport, workout_title: '恢复性活动' },
    workout: { ...strengthWorkout, title: '恢复性活动', volume_kg: 0, highlights: [] },
    prs: [],
    week_count: 2,
  },
  // 6. 混合（力量 + 有氧，两行指标）
  mixed: {
    report: { ...baseReport, workout_title: '力量 + 跑步' },
    workout: {
      ...strengthWorkout, title: '力量 + 跑步', workout_kind: 'mixed',
      distance_m: 3000, avg_hr: 132,
      cardio: { distance_m: 3000, avg_hr: 132, duration_s: 4020, calories: 486 },
    },
    prs: [{ movement: '杠铃卧推', weight: 65, unit: 'kg', reps: 8 }],
    week_count: 4,
  },
}

mkdirSync(outDir, { recursive: true })
for (const [name, payload] of Object.entries(shapes)) {
  const html = `<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>poster demo ${name}</title>
<style>body{margin:0;background:#ffffff}canvas{display:block}</style>
</head>
<body>
<script>
${statusJs}
${posterJs}
const payload = ${JSON.stringify(payload)}
const canvas = renderPosterCanvas(buildPosterData(payload))
canvas.style.width = '1080px'
canvas.style.height = '1440px'
document.body.appendChild(canvas)
</script>
</body>
</html>
`
  const out = join(outDir, `poster-demo-${name}.html`)
  writeFileSync(out, html, 'utf8')
  console.log(`poster demo written: ${out}`)
}
