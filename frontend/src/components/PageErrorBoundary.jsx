import { Component } from 'react'

export default class PageErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <section role="alert" className="mx-auto max-w-lg rounded-2xl border border-red-200 bg-white p-6 text-center shadow-sm dark:border-red-900/60 dark:bg-gray-900">
        <p className="text-lg font-bold text-gray-950 dark:text-white">页面暂时无法显示</p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">请刷新后重试。如果问题仍然存在，可以先返回训练日历。</p>
        <div className="mt-5 flex justify-center gap-3">
          <button type="button" onClick={() => window.location.reload()} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
            刷新页面
          </button>
          <a href="/" className="rounded-xl border border-gray-200 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800">
            返回日历
          </a>
        </div>
      </section>
    )
  }
}
