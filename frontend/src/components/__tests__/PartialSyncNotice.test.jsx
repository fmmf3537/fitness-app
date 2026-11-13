import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PartialSyncNotice from '../PartialSyncNotice'

describe('PartialSyncNotice', () => {
  it('test_renders_nothing_when_no_skipped', () => {
    const { container } = render(
      <PartialSyncNotice syncResult={{ written: 5, skipped: 0, excluded: 0, skipped_movements: [] }} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('test_renders_counts', () => {
    render(
      <PartialSyncNotice
        syncResult={{
          written: 2,
          skipped: 1,
          excluded: 0,
          skipped_movements: [{ name: '动作A', reason: 'no_mapping' }],
        }}
      />,
    )
    expect(screen.getByTestId('partial-sync-notice')).toHaveTextContent('已写入 2 个动作')
    expect(screen.getByTestId('partial-sync-notice')).toHaveTextContent('跳过 1 个')
  })

  it('test_lists_skipped_movements', () => {
    render(
      <PartialSyncNotice
        syncResult={{
          written: 1,
          skipped: 2,
          excluded: 0,
          skipped_movements: [
            { name: '杠铃深蹲', reason: 'MAPPING_MISSING' },
            { name: '哑铃推举', reason: 'UNMAPPED' },
          ],
        }}
      />,
    )
    const notice = screen.getByTestId('partial-sync-notice')
    expect(notice).toHaveTextContent('杠铃深蹲')
    expect(notice).toHaveTextContent('MAPPING_MISSING')
    expect(notice).toHaveTextContent('哑铃推举')
    expect(notice).toHaveTextContent('UNMAPPED')
  })

  it('test_truncates_after_eight', () => {
    const skipped_movements = Array.from({ length: 10 }, (_, i) => ({
      name: `动作${i + 1}`,
      reason: 'skip',
    }))
    render(
      <PartialSyncNotice
        syncResult={{ written: 0, skipped: 10, excluded: 0, skipped_movements }}
      />,
    )
    const notice = screen.getByTestId('partial-sync-notice')
    expect(notice).toHaveTextContent('动作1')
    expect(notice).toHaveTextContent('动作8')
    expect(notice).not.toHaveTextContent('动作9')
    expect(notice).not.toHaveTextContent('动作10')
    expect(notice).toHaveTextContent('还有 2 个')
  })

  it('test_shows_excluded_hint', () => {
    render(
      <PartialSyncNotice
        syncResult={{
          written: 2,
          skipped: 1,
          excluded: 3,
          skipped_movements: [{ name: 'X', reason: 'y' }],
        }}
      />,
    )
    const notice = screen.getByTestId('partial-sync-notice')
    expect(notice).toHaveTextContent('按产品定义不写入')
    expect(notice).toHaveTextContent('3')
  })
})
