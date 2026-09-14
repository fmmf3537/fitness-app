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
    <div data-testid="coach-hub" className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b bg-white px-4 py-3">
        <h1 className="text-xl font-bold text-gray-900">教练中心</h1>
      </div>

      <div className="px-4 pt-3">
        <div className="flex rounded-lg bg-gray-100 p-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'chat'}
            data-testid="coach-tab-chat"
            onClick={() => setTab('chat')}
            className={`min-h-[40px] flex-1 rounded-md text-sm font-medium ${
              tab === 'chat' ? 'bg-white shadow-sm' : 'text-gray-600'
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
              tab === 'prefs' ? 'bg-white shadow-sm' : 'text-gray-600'
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
