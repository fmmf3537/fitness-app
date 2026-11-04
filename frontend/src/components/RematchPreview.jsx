import BottomSheet from './BottomSheet'
import Button from './ui/Button'
import { formatDateTime, formatDuration } from '../utils/status'

function SourceCard({ title, name, time }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-950">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{title}</p>
      <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">{name || '无标题'}</p>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{time}</p>
    </div>
  )
}

export default function RematchPreview({ preview, resolving, error, onCancel, onConfirm }) {
  const actionable = preview?.action === 'merge' || preview?.action === 'candidate'
  const xunji = preview?.xunji_train
  const garmin = preview?.garmin_activity
  return (
    <BottomSheet
      open={Boolean(preview)}
      onClose={resolving ? undefined : onCancel}
      title="重新匹配预览"
      footer={(
        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={onCancel} disabled={resolving}>
            {actionable ? '取消' : '关闭'}
          </Button>
          {actionable && (
            <Button variant="primary" className="flex-1" onClick={onConfirm} disabled={resolving}>
              {resolving ? '正在处理…' : preview.action === 'merge' ? '确认合并' : '转入待确认'}
            </Button>
          )}
        </div>
      )}
    >
      {preview && (
        <div className="space-y-4" data-testid="rematch-preview">
          {error && <p role="alert" className="text-sm text-red-600">重新匹配失败：{error}</p>}
          {preview.action === 'unmatched' ? (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              没有找到符合时间条件的另一侧单边训练，本次未修改任何数据。
            </p>
          ) : (
            <>
              <p className="text-sm text-gray-600 dark:text-gray-300">
                已找到同日单边训练。确认前请核对两侧是否为同一次运动。
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <SourceCard
                  title="训记"
                  name={xunji?.title}
                  time={formatDateTime(xunji?.start_ms)}
                />
                <SourceCard
                  title="佳明"
                  name={garmin?.name}
                  time={formatDateTime(garmin?.start_ts)}
                />
              </div>
              <div className="rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700">
                <p className="font-medium text-gray-900 dark:text-gray-100">
                  时间重叠 {Math.round((preview.overlap_ratio || 0) * 100)}%
                </p>
                {preview.action === 'merge' ? (
                  <p className="mt-1 text-gray-600 dark:text-gray-300">
                    达到自动匹配条件。确认后保留训记动作，并补充佳明时长
                    {preview.workout?.duration_s != null ? `（${formatDuration(preview.workout.duration_s)}）` : ''}
                    、热量和心率，不会新增重复训练。
                  </p>
                ) : (
                  <p className="mt-1 text-gray-600 dark:text-gray-300">
                    时间接近但重叠不足。确认后转为双边待确认，再由你选择合并或保持分开。
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </BottomSheet>
  )
}
