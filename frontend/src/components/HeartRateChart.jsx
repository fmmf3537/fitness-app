import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import useIsMobile from '../hooks/useIsMobile'
import { CHART_PALETTE, mergeMobileOption } from '../utils/echartsMobile'

export default function HeartRateChart({ data }) {
  const ref = useRef(null)
  const isMobile = useIsMobile()

  useEffect(() => {
    if (!ref.current) return undefined
    const chart = echarts.init(ref.current)
    const base = {
      aria: { enabled: true },
      title: { text: '心率曲线', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: {
        type: 'category',
        data: (data || []).map((p) => p.t),
        name: '时间',
      },
      yAxis: { type: 'value', name: 'bpm' },
      series: [
        {
          type: 'line',
          data: (data || []).map((p) => p.hr),
          smooth: true,
          showSymbol: false,
          lineStyle: { color: CHART_PALETTE[3] },
          areaStyle: { opacity: 0.1 },
        },
      ],
    }
    chart.setOption(isMobile ? mergeMobileOption(base) : base)
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
    }
  }, [data, isMobile])

  return (
    <div
      ref={ref}
      data-testid="hr-chart"
      role="img"
      aria-label="心率曲线图"
      className="h-72 w-full"
    />
  )
}
