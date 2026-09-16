import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'

/** UIX-06：embedded 时不渲染页首 h1（由 CoachHubPage 承载） */
export default function CoachPreferencesPage({ embedded = false }) {
  const [preferences, setPreferences] = useState([])
  const [drafts, setDrafts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingPref, setEditingPref] = useState(null) // null | {id?, content, tags}
  const [saving, setSaving] = useState(false)
  const [resolveDraftId, setResolveDraftId] = useState(null)
  const [deleteTargetId, setDeleteTargetId] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    return Promise.all([api('/api/coach/preferences'), api('/api/coach/drafts')])
      .then(([prefData, draftData]) => {
        setPreferences(prefData.preferences || [])
        setDrafts(draftData.drafts || [])
      })
      .catch((err) => {
        setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (payload) => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api('/api/coach/preferences', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setEditingPref(null)
      setMessage('已保存')
      await load()
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleUpdate = async (prefId, payload) => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api(`/api/coach/preferences/${prefId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      setEditingPref(null)
      setMessage('已保存')
      await load()
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteConfirm = async () => {
    const prefId = deleteTargetId
    setDeleteTargetId(null)
    if (prefId == null) return
    setError('')
    setMessage('')
    try {
      await api(`/api/coach/preferences/${prefId}`, { method: 'DELETE' })
      setMessage('已删除')
      await load()
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
    }
  }

  const handleAcceptDraft = async (draftId) => {
    setResolveDraftId(draftId)
    setError('')
    setMessage('')
    try {
      await api(`/api/coach/drafts/${draftId}/accept`, { method: 'POST' })
      setMessage('已采纳')
      await load()
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
    } finally {
      setResolveDraftId(null)
    }
  }

  const handleRejectDraft = async (draftId) => {
    setResolveDraftId(draftId)
    setError('')
    setMessage('')
    try {
      await api(`/api/coach/drafts/${draftId}/reject`, { method: 'POST' })
      setMessage('已忽略')
      await load()
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message)
    } finally {
      setResolveDraftId(null)
    }
  }

  const handleSaveModal = async (e) => {
    e.preventDefault()
    if (!editingPref) return
    const content = (editingPref.content || '').trim()
    if (!content) {
      setError('请填写须知内容')
      return
    }
    const tags = (editingPref.tags || '').trim()
    const payload = { content, tags: tags || null }
    if (editingPref.id != null) {
      await handleUpdate(editingPref.id, payload)
    } else {
      await handleCreate(payload)
    }
  }

  return (
    <div className="space-y-4" data-testid="coach-preferences-page">
      <div className={`flex items-center ${embedded ? 'justify-end' : 'justify-between'}`}>
        {!embedded && <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">教练须知</h1>}
        <Button
          variant="primary"
          testId="create-preference-btn"
          onClick={() => setEditingPref({ content: '', tags: '' })}
        >
          新建须知
        </Button>
      </div>

      {error && (
        <ErrorState message={error} onRetry={load} testId="preferences-error" />
      )}
      {message && <p className="text-sm text-green-600">{message}</p>}
      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}

      <section data-testid="preferences-list">
        {preferences.length === 0 && !loading ? (
          <EmptyState
            title="暂无须知"
            description="在下方添加你的长期偏好（如伤病/忌讳/目标），AI 会在下次点评时参考。"
            action={
              <Button
                variant="primary"
                onClick={() => setEditingPref({ content: '', tags: '' })}
              >
                新建须知
              </Button>
            }
          />
        ) : null}
        {preferences.length > 0 ? (
          <ul>
            {preferences.map((pref) => (
              <li key={pref.id} data-testid={`preference-${pref.id}`} className="mb-3">
                <Card>
                  <p className="whitespace-pre-wrap text-sm text-gray-900 dark:text-gray-100">{pref.content}</p>
                  {pref.tags ? (
                    <p className="mt-1 text-xs text-gray-600 dark:text-gray-400" data-testid={`preference-tags-${pref.id}`}>
                      {pref.tags}
                    </p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    {pref.source ? (
                      <Badge variant="gray">{pref.source}</Badge>
                    ) : null}
                    {pref.category ? (
                      <Badge variant="gray">{pref.category}</Badge>
                    ) : null}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="secondary"
                      testId={`edit-preference-${pref.id}`}
                      onClick={() =>
                        setEditingPref({
                          id: pref.id,
                          content: pref.content,
                          tags: pref.tags || '',
                        })
                      }
                    >
                      编辑
                    </Button>
                    <Button
                      variant="danger"
                      testId={`delete-preference-${pref.id}`}
                      onClick={() => setDeleteTargetId(pref.id)}
                    >
                      删除
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {drafts.length > 0 && (
        <section data-testid="drafts-section" className="rounded-lg bg-amber-50 dark:bg-amber-950/50 p-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI 草稿（待确认）</h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">由最近一周复盘从对话中自动提炼</p>
          <ul className="mt-3">
            {drafts.map((draft) => (
              <li key={draft.id} data-testid={`draft-${draft.id}`} className="mb-3">
                <Card>
                  <p className="whitespace-pre-wrap text-sm text-gray-900 dark:text-gray-100">{draft.content}</p>
                  {draft.tags ? (
                    <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">{draft.tags}</p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    {draft.source ? (
                      <Badge variant="gray">{draft.source}</Badge>
                    ) : null}
                    {draft.created_at ? (
                      <Badge variant="gray">{draft.created_at}</Badge>
                    ) : null}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="primary"
                      testId={`accept-draft-${draft.id}`}
                      onClick={() => handleAcceptDraft(draft.id)}
                      disabled={resolveDraftId === draft.id}
                    >
                      采纳
                    </Button>
                    <Button
                      variant="secondary"
                      testId={`reject-draft-${draft.id}`}
                      onClick={() => handleRejectDraft(draft.id)}
                      disabled={resolveDraftId === draft.id}
                    >
                      忽略
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editingPref && (
        <div
          data-testid="preference-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          role="dialog"
          aria-modal="true"
        >
          <form
            onSubmit={handleSaveModal}
            className="w-full max-w-md rounded-lg bg-white dark:bg-gray-900 p-4 shadow-lg mb-[env(safe-area-inset-bottom)]"
          >
            <h3 className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">
              {editingPref.id != null ? '编辑须知' : '新建须知'}
            </h3>
            <label className="mb-1 block text-xs text-gray-600 dark:text-gray-400" htmlFor="pref-content">
              内容
            </label>
            <textarea
              id="pref-content"
              data-testid="pref-content-input"
              required
              rows={4}
              value={editingPref.content}
              onChange={(e) => setEditingPref({ ...editingPref, content: e.target.value })}
              className="mb-3 w-full rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
            />
            <label className="mb-1 block text-xs text-gray-600 dark:text-gray-400" htmlFor="pref-tags">
              标签（逗号分隔，可选）
            </label>
            <input
              id="pref-tags"
              data-testid="pref-tags-input"
              type="text"
              value={editingPref.tags}
              onChange={(e) => setEditingPref({ ...editingPref, tags: e.target.value })}
              className="mb-4 w-full rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
              placeholder="伤病,忌讳,目标"
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                testId="pref-cancel-btn"
                onClick={() => setEditingPref(null)}
              >
                取消
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="compact"
                testId="pref-save-btn"
                disabled={saving}
              >
                {saving ? '保存中…' : '保存'}
              </Button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        open={deleteTargetId != null}
        title="确定删除该须知？"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTargetId(null)}
      />
    </div>
  )
}
