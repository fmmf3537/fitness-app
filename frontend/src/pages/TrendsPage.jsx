import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import TrendChart from '../components/TrendChart'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import IconChip from '../components/ui/IconChip'
import PillGroup from '../components/ui/PillGroup'
import Skeleton from '../components/ui/Skeleton'
import useIsMobile from '../hooks/useIsMobile'
import usePullToRefresh from '../hooks/usePullToRefresh'
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

function ChartCard({ title, insight, option, testId, empty, className = '' }) {
  return (
    <Card className={`overflow-hidden ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-bold text-ink-900 dark:text-gray-100">{title}</h2>
        {insight && <span className="shrink-0 text-[11px] text-ink-500 dark:text-gray-400">{insight}</span>}
      </div>
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
  const latestWeek = data.weekly_volume?.at(-1)
  const summary = data.summary || {}
  const volumeDelta = summary.volume_change_pct
  const latestWeight = data.body_metrics?.weight?.at(-1)
  const { pulling, bind: pullBind } = usePullToRefresh(load)

  return (
    <div className="space-y-4" {...pullBind}>
      {pulling && <p role="status" className="text-center text-xs text-brand-600">正在刷新趋势…</p>}
      <PageHeader title="训练趋势" subtitle="用真实训练与身体数据观察近期变化" />

      <div className="mt-4 inline-flex rounded-full border border-line bg-white p-1 shadow-card dark:border-gray-800 dark:bg-gray-900">
        <PillGroup
          options={WEEK_OPTIONS}
          value={weeks}
          onChange={setWeeks}
          testId="weeks-toggle"
          ariaLabel="趋势周期"
        />
      </div>

      {!loading && !error && !empty && (
        <div className="grid grid-cols-3 gap-2 sm:gap-3" data-testid="trend-hero">
          {[
            { label: '本周训练', value: summary.current_week_sessions != null ? `${summary.current_week_sessions} 次` : null, icon: 'flame', chip: 'violet' },
            { label: '连续训练', value: summary.training_streak_days != null ? `${summary.training_streak_days} 天` : null, icon: 'clock', chip: 'blue' },
            { label: '最佳负重', value: summary.best_set ? `${summary.best_set.movement} ${summary.best_set.weight}kg×${summary.best_set.reps}` : null, icon: 'dumbbell', chip: 'green' },
          ].map(({ label, value, icon, chip }) => value != null && (
            <Card key={label} className="min-w-0 p-3">
              <IconChip icon={icon} variant={chip} />
              <p className="mt-2 truncate text-base font-black text-ink-900 dark:text-white sm:text-lg">{value}</p>
              <p className="mt-0.5 text-[11px] text-ink-500 dark:text-gray-300">{label}</p>
            </Card>
          ))}
        </div>
      )}

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
        empty ? (
          <EmptyState title="暂无趋势数据" description="先同步或录入真实训练，完成一次训练后即可查看趋势" action={<a href="/" className="inline-flex min-h-11 items-center rounded-xl bg-gradient-brand px-4 text-sm font-semibold text-white shadow-glow">去同步训练</a>} />
        ) : <div className="grid gap-4 md:grid-cols-2">
          <ChartCard
            title="每周总容量（吨）"
            insight={latestWeek ? `最近一周 ${latestWeek.volume_tons} 吨${volumeDelta == null ? '' : `，较前一周 ${volumeDelta >= 0 ? '+' : ''}${volumeDelta.toFixed(1)}%`}` : null}
            option={buildWeeklyVolumeOption(data.weekly_volume, chartOpts)}
            testId="trend-chart-volume"
            empty={empty}
            className="md:col-span-2"
          />
          <ChartCard
            title="各部位训练频次"
            insight="各部位训练次数分布"
            option={buildBodyPartOption(data.body_part_frequency, chartOpts)}
            testId="trend-chart-bodypart"
            empty={empty}
          />
          <ChartCard
            title="体重/体脂曲线"
            insight={latestWeight ? `最新体重 ${latestWeight.value} kg` : null}
            option={buildBodyMetricOption(data.body_metrics, chartOpts)}
            testId="trend-chart-bodymetric"
            empty={empty}
          />
          <ChartCard
            title="睡眠-容量散点"
            insight={summary.sleep_under_6h_volume_change_pct == null ? '每个点代表一天的真实睡眠与训练容量' : `睡眠少于 6 小时时，训练容量平均变化 ${summary.sleep_under_6h_volume_change_pct >= 0 ? '+' : ''}${summary.sleep_under_6h_volume_change_pct}%`}
            option={buildSleepVolumeOption(data.sleep_volume, chartOpts)}
            testId="trend-chart-sleep"
            empty={empty}
          />
        </div>
      )}
    </div>
  )
}
