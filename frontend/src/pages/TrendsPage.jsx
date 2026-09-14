import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import TrendChart from '../components/TrendChart'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import PillGroup from '../components/ui/PillGroup'
import Skeleton from '../components/ui/Skeleton'
import useIsMobile from '../hooks/useIsMobile'
import {
  buildBodyMetricOption,
  buildBodyPartOption,
  buildSleepVolumeOption,
  buildWeeklyVolumeOption,
} from '../utils/trends'

// 保留备查：空数据 option 构造用，加载完成后的空态改用 EmptyState，不渲染空坐标轴
const EMPTY_TRENDS = {
  weekly_volume: [],
  body_part_frequency: [],
  body_metrics: {},
  sleep_volume: [],
}

const WEEK_OPTIONS = [
  { value: 4, label: '4 周' },
  { value: 12, label: '12 周' },
]

function isTrendsEmpty(data) {
  if (!data) return true
  const metrics = data.body_metrics || {}
  const hasMetric = Object.values(metrics).some((arr) => arr?.length > 0)
  return (
    !(data.weekly_volume?.length > 0) &&
    !(data.body_part_frequency?.length > 0) &&
    !hasMetric &&
    !(data.sleep_volume?.length > 0)
  )
}

function ChartCard({ title, option, testId, empty }) {
  return (
    <Card>
      <h2 className="mb-2 text-sm font-medium text-gray-900 dark:text-gray-100">{title}</h2>
      {empty ? (
        <EmptyState
          title="暂无趋势数据"
          description="完成一次训练后即可查看趋势"
        />
      ) : (
        <TrendChart option={option} testId={testId} ariaLabel={title} />
      )}
    </Card>
  )
}

export default function TrendsPage() {
  const isMobile = useIsMobile()
  const [weeks, setWeeks] = useState(4)
  const [trends, setTrends] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    return api(`/api/stats/trends?weeks=${weeks}`)
      .then((data) => setTrends(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
      .finally(() => setLoading(false))
  }, [weeks])

  useEffect(() => {
    load()
  }, [load])

  const chartOpts = { mobile: isMobile }
  const empty = !loading && !error && isTrendsEmpty(trends)
  // EMPTY_TRENDS 仅作空结构参考，有数据时用真实 trends
  const data = empty ? EMPTY_TRENDS : trends || EMPTY_TRENDS

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">训练趋势</h1>
        <PillGroup
          options={WEEK_OPTIONS}
          value={weeks}
          onChange={setWeeks}
          testId="weeks-toggle"
        />
      </div>

      {error && (
        <ErrorState message={error} onRetry={load} testId="trends-error" />
      )}

      {loading && (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      )}

      {!loading && !error && (
        <div className="grid gap-4 md:grid-cols-2">
          <ChartCard
            title="每周总容量（吨）"
            option={buildWeeklyVolumeOption(data.weekly_volume, chartOpts)}
            testId="trend-chart-volume"
            empty={empty}
          />
          <ChartCard
            title="各部位训练频次"
            option={buildBodyPartOption(data.body_part_frequency, chartOpts)}
            testId="trend-chart-bodypart"
            empty={empty}
          />
          <ChartCard
            title="体重/体脂曲线"
            option={buildBodyMetricOption(data.body_metrics, chartOpts)}
            testId="trend-chart-bodymetric"
            empty={empty}
          />
          <ChartCard
            title="睡眠-容量散点"
            option={buildSleepVolumeOption(data.sleep_volume, chartOpts)}
            testId="trend-chart-sleep"
            empty={empty}
          />
        </div>
      )}
    </div>
  )
}
