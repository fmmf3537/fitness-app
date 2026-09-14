import { useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'

function ScreenshotIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  )
}

function FileIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function HistoryIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

const CARDS = [
  {
    testId: 'import-card-screenshot',
    to: '/screenshot-import',
    title: '截图识别补录',
    description: '拍训记 App 截图，AI 自动识别动作与重量',
    Icon: ScreenshotIcon,
  },
  {
    testId: 'import-card-fit',
    to: '/fit-import',
    title: '佳明文件导入',
    description: '导入 .fit/.tcx/.gpx/.kml 原始运动文件',
    Icon: FileIcon,
  },
  {
    testId: 'import-card-backfill',
    to: '/backfill',
    title: '历史数据补录',
    description: '按时间段批量拉取训记 / 佳明历史数据',
    Icon: HistoryIcon,
  },
]

/**
 * 数据导入聚合页：三张卡片入口，既有导入路由保留。
 */
export default function ImportHubPage() {
  const navigate = useNavigate()

  return (
    <div data-testid="import-hub" className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">数据导入</h1>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">三种方式把训练数据同步进看板</p>
      </div>

      <div className="space-y-3">
        {CARDS.map(({ testId, to, title, description, Icon }) => (
          <div
            key={testId}
            data-testid={testId}
            role="link"
            tabIndex={0}
            className="cursor-pointer"
            onClick={() => navigate(to)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                navigate(to)
              }
            }}
          >
            <Card>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600">
                  <Icon />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</p>
                  <p className="text-xs text-gray-600 dark:text-gray-400">{description}</p>
                </div>
                <Button
                  variant="secondary"
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(to)
                  }}
                >
                  进入
                </Button>
              </div>
            </Card>
          </div>
        ))}
      </div>
    </div>
  )
}
