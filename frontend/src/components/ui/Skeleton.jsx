/**
 * 骨架屏原语。用途：淘汰全站 15+ 处裸文本"加载中…"。
 */
export default function Skeleton({ className = '', testId }) {
  return (
    <div
      data-testid={testId}
      className={`animate-pulse rounded bg-gray-200 dark:bg-gray-800 ${className}`}
    />
  )
}

/** 多行文本骨架：首行 full、末行 2/3、中间 5/6 */
export function SkeletonText({ lines = 3, testId }) {
  return (
    <div data-testid={testId}>
      {Array.from({ length: lines }, (_, i) => {
        let width = 'w-5/6'
        if (i === 0) width = 'w-full'
        if (i === lines - 1) width = 'w-2/3'
        const mt = i === 0 ? '' : 'mt-2'
        return (
          <div
            key={i}
            className={`h-3 animate-pulse rounded bg-gray-100 dark:bg-gray-700 ${width} ${mt}`.trim()}
          />
        )
      })}
    </div>
  )
}
