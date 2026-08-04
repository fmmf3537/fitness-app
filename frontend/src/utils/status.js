export const STATUS_COLORS = {
  auto_matched: 'bg-green-500',
  manual_matched: 'bg-blue-500',
  xunji_only: 'bg-yellow-400',
  garmin_only: 'bg-purple-500',
  pending: 'bg-orange-500',
}

export const STATUS_LABELS = {
  auto_matched: '自动匹配',
  manual_matched: '手动匹配',
  xunji_only: '仅训记',
  garmin_only: '仅佳明',
  pending: '待确认',
}

export function statusColor(status) {
  return STATUS_COLORS[status] || 'bg-gray-400'
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

export function formatDuration(seconds) {
  if (seconds == null) return '-'
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `${mins} 分钟`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m === 0 ? `${h} 小时` : `${h} 小时 ${m} 分钟`
}

export function formatDateTime(value) {
  if (value == null) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
