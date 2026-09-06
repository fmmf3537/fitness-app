import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export default function CoachPreferencesPage() {
  const [preferences, setPreferences] = useState([])
  const [drafts, setDrafts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingPref, setEditingPref] = useState(null) // null | {id?, content, tags}
  const [saving, setSaving] = useState(false)
  const [resolveDraftId, setResolveDraftId] = useState(null)

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

  const handleDelete = async (prefId) => {
    if (!window.confirm('确定删除该须知？')) return
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
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">教练须知</h1>
        <button
          type="button"
          data-testid="create-preference-btn"
          onClick={() => setEditingPref({ content: '', tags: '' })}
          className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          新建须知
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {message && <p className="text-sm text-green-600">{message}</p>}
      {loading && <p className="text-sm text-gray-500">加载中…</p>}

      <section data-testid="preferences-list">
        {preferences.length === 0 && !loading ? (
          <p className="text-sm text-gray-500">
            暂无须知。在下方添加你的长期偏好（如伤病/忌讳/目标），AI 会在下次点评时参考。
          </p>
        ) : (
          <ul>
            {preferences.map((pref) => (
              <li
                key={pref.id}
                data-testid={`preference-${pref.id}`}
                className="mb-3 rounded-lg bg-white p-4 shadow-sm"
              >
                <p className="whitespace-pre-wrap text-sm text-gray-900">{pref.content}</p>
                {pref.tags ? (
                  <p className="mt-1 text-xs text-gray-500" data-testid={`preference-tags-${pref.id}`}>
                    {pref.tags}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  {pref.source ? (
                    <span className="mr-2 rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {pref.source}
                    </span>
                  ) : null}
                  {pref.category ? (
                    <span className="mr-2 rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {pref.category}
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    data-testid={`edit-preference-${pref.id}`}
                    onClick={() =>
                      setEditingPref({
                        id: pref.id,
                        content: pref.content,
                        tags: pref.tags || '',
                      })
                    }
                    className="rounded-md bg-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-300"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    data-testid={`delete-preference-${pref.id}`}
                    onClick={() => handleDelete(pref.id)}
                    className="rounded-md bg-red-600 px-3 py-2 text-sm text-white hover:bg-red-700"
                  >
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {drafts.length > 0 && (
        <section data-testid="drafts-section" className="rounded-lg bg-amber-50 p-4">
          <h2 className="text-lg font-semibold text-gray-900">AI 草稿（待确认）</h2>
          <p className="mt-1 text-sm text-gray-600">由最近一周复盘从对话中自动提炼</p>
          <ul className="mt-3">
            {drafts.map((draft) => (
              <li
                key={draft.id}
                data-testid={`draft-${draft.id}`}
                className="mb-3 rounded-lg bg-white p-4 shadow-sm"
              >
                <p className="whitespace-pre-wrap text-sm text-gray-900">{draft.content}</p>
                {draft.tags ? (
                  <p className="mt-1 text-xs text-gray-500">{draft.tags}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  {draft.source ? (
                    <span className="mr-2 rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {draft.source}
                    </span>
                  ) : null}
                  {draft.created_at ? (
                    <span className="mr-2 rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {draft.created_at}
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    data-testid={`accept-draft-${draft.id}`}
                    onClick={() => handleAcceptDraft(draft.id)}
                    disabled={resolveDraftId === draft.id}
                    className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    采纳
                  </button>
                  <button
                    type="button"
                    data-testid={`reject-draft-${draft.id}`}
                    onClick={() => handleRejectDraft(draft.id)}
                    disabled={resolveDraftId === draft.id}
                    className="rounded-md bg-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-300 disabled:opacity-50"
                  >
                    忽略
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editingPref && (
        <div
          data-testid="preference-modal"
          className="fixed inset-0 z-10 flex items-center justify-center bg-black/30"
          role="dialog"
          aria-modal="true"
        >
          <form
            onSubmit={handleSaveModal}
            className="w-full max-w-md rounded-lg bg-white p-4 shadow-lg"
          >
            <h3 className="mb-3 text-sm font-medium text-gray-900">
              {editingPref.id != null ? '编辑须知' : '新建须知'}
            </h3>
            <label className="mb-1 block text-xs text-gray-600" htmlFor="pref-content">
              内容
            </label>
            <textarea
              id="pref-content"
              data-testid="pref-content-input"
              required
              rows={4}
              value={editingPref.content}
              onChange={(e) => setEditingPref({ ...editingPref, content: e.target.value })}
              className="mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            />
            <label className="mb-1 block text-xs text-gray-600" htmlFor="pref-tags">
              标签（逗号分隔，可选）
            </label>
            <input
              id="pref-tags"
              data-testid="pref-tags-input"
              type="text"
              value={editingPref.tags}
              onChange={(e) => setEditingPref({ ...editingPref, tags: e.target.value })}
              className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
              placeholder="伤病,忌讳,目标"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                data-testid="pref-cancel-btn"
                onClick={() => setEditingPref(null)}
                className="rounded-md bg-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-300"
              >
                取消
              </button>
              <button
                type="submit"
                data-testid="pref-save-btn"
                disabled={saving}
                className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
