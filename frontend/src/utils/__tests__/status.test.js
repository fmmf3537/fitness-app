import { describe, it, expect } from 'vitest'
import {
  STATUS_COLORS,
  STATUS_LABELS,
  statusColor,
  statusLabel,
  formatDuration,
  formatDateTime,
} from '../status'

describe('statusColor / statusLabel', () => {
  it('已知状态返回映射值', () => {
    for (const key of Object.keys(STATUS_COLORS)) {
      expect(statusColor(key)).toBe(STATUS_COLORS[key])
      expect(statusLabel(key)).toBe(STATUS_LABELS[key])
    }
  })

  it('未知状态回退', () => {
    expect(statusColor('mystery')).toBe('bg-gray-400')
    expect(statusLabel('mystery')).toBe('mystery')
  })
})

describe('formatDuration', () => {
  it('null/undefined 返回 -', () => {
    expect(formatDuration(null)).toBe('-')
    expect(formatDuration(undefined)).toBe('-')
  })

  it('不足 1 小时显示分钟', () => {
    expect(formatDuration(3213)).toBe('54 分钟')
  })

  it('整小时', () => {
    expect(formatDuration(3600)).toBe('1 小时')
  })

  it('小时+分钟', () => {
    expect(formatDuration(9569)).toBe('2 小时 39 分钟')
  })
})

describe('formatDateTime', () => {
  it('null 返回 -', () => {
    expect(formatDateTime(null)).toBe('-')
  })

  it('非法值原样返回字符串', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('合法时间戳格式化为 YYYY-MM-DD HH:mm', () => {
    const result = formatDateTime(new Date(2026, 7, 4, 9, 5).getTime())
    expect(result).toBe('2026-08-04 09:05')
  })
})
