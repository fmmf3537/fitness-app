import { useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import CoachChatPage from './CoachChatPage'
import CoachPreferencesPage from './CoachPreferencesPage'

/**
 * 教练中心聚合页：分段切换「聊天 / 教练须知」。
 * 样式按原型 iOS 式灰底白卡分段控件（非 PillGroup）。
 */
export default function CoachHubPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') === 'prefs' ? 'prefs' : 'chat'

  const setTab = (next) => {
    setSearchParams(next === 'prefs' ? { tab: 'prefs' } : {}, { replace: true })
  }

  return (
    <div data-testid="coach-hub" className="flex min-h-[calc(100dvh-10.5rem)] flex-col md:min-h-0">
      <PageHeader title="教练中心" subtitle="和你的 AI 教练聊聊" />

      <div className="pb-3 md:px-4 md:pt-3">
        <div className="flex rounded-full border border-line bg-white p-1 shadow-card dark:border-gray-800 dark:bg-gray-900 md:dark:bg-gray-800 md:dark:border-transparent" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'chat'}
            data-testid="coach-tab-chat"
            onClick={() => setTab('chat')}
            className={`min-h-[40px] flex-1 rounded-full text-sm font-semibold transition ${
              tab === 'chat' ? 'bg-gradient-brand text-white shadow-glow' : 'text-ink-500 dark:text-gray-400'
            }`}
          >
            聊天
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'prefs'}
            data-testid="coach-tab-prefs"
            onClick={() => setTab('prefs')}
            className={`min-h-[40px] flex-1 rounded-full text-sm font-semibold transition ${
              tab === 'prefs' ? 'bg-gradient-brand text-white shadow-glow' : 'text-ink-500 dark:text-gray-400'
            }`}
          >
            教练须知
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {tab === 'prefs' ? (
          <CoachPreferencesPage embedded />
        ) : (
          <CoachChatPage embedded />
        )}
      </div>
    </div>
  )
}
