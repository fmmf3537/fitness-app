import { useSearchParams } from 'react-router-dom'
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
      <div className="flex items-center justify-between px-1 pb-3 md:border-b md:bg-white md:px-4 md:py-3 dark:md:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">教练中心</h1>
      </div>

      <div className="pb-3 md:px-4 md:pt-3">
        <div className="flex rounded-lg bg-gray-100 dark:bg-gray-800 p-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'chat'}
            data-testid="coach-tab-chat"
            onClick={() => setTab('chat')}
            className={`min-h-[40px] flex-1 rounded-md text-sm font-medium ${
              tab === 'chat' ? 'bg-white dark:bg-gray-900 shadow-sm' : 'text-gray-600 dark:text-gray-400'
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
            className={`min-h-[40px] flex-1 rounded-md text-sm font-medium ${
              tab === 'prefs' ? 'bg-white dark:bg-gray-900 shadow-sm' : 'text-gray-600 dark:text-gray-400'
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
