import { useEffect, useState } from 'react'
import { api } from '../api/client'
import TrendChart from '../components/TrendChart'
import useIsMobile from '../hooks/useIsMobile'
import {
  buildBodyMetricOption,
  buildBodyPartOption,
  buildSleepVolumeOption,
  buildWeeklyVolumeOption,
} from '../utils/trends'

const EMPTY_TRENDS = {
  weekly_volume: [],
  body_part_frequency: [],
  body_metrics: {},
  sleep_volume: [],
}

function ChartCard({ title, option, testId }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="mb-2 text-sm font-medium text-gray-900">{title}</h2>
      <TrendChart option={option} testId={testId} />
    </section>
  )
}

export default function TrendsPage() {
  const isMobile = useIsMobile()
  const [weeks, setWeeks] = useState(4)
  const [trends, setTrends] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    api(`/api/stats/trends?weeks=${weeks}`)
      .then((data) => setTrends(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
      .finally(() => setLoading(false))
  }, [weeks])

  const data = trends || EMPTY_TRENDS
  const chartOpts = { mobile: isMobile }
  const toggleClass = (value) =>
    `rounded-md px-3 py-2 text-sm font-medium ${
      weeks === value ? 'bg-indigo-600 text-white' : 'text-gray-700 hover:bg-gray-200'
    }`

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">训练趋势</h1>
        <div className="flex gap-1">
          <button
            data-testid="weeks-toggle-4"
            onClick={() => setWeeks(4)}
            className={toggleClass(4)}
          >
            4 周
          </button>
          <button
            data-testid="weeks-toggle-12"
            onClick={() => setWeeks(12)}
            className={toggleClass(12)}
          >
            12 周
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

      {!error && (
        <div className="grid gap-4 md:grid-cols-2">
          <ChartCard
            title="每周总容量（吨）"
            option={buildWeeklyVolumeOption(data.weekly_volume, chartOpts)}
            testId="trend-chart-volume"
          />
          <ChartCard
            title="各部位训练频次"
            option={buildBodyPartOption(data.body_part_frequency, chartOpts)}
            testId="trend-chart-bodypart"
          />
          <ChartCard
            title="体重/体脂曲线"
            option={buildBodyMetricOption(data.body_metrics, chartOpts)}
            testId="trend-chart-bodymetric"
          />
          <ChartCard
            title="睡眠-容量散点"
            option={buildSleepVolumeOption(data.sleep_volume, chartOpts)}
            testId="trend-chart-sleep"
          />
        </div>
      )}
    </div>
  )
}
