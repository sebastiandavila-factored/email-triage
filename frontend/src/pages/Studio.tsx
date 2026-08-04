import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { Category, PromptDraft, PromptPreview, PromptVersion, TriageExample } from '../api'
import { can } from '../rbac'
import { WorkspaceSwitcher } from '../components/WorkspaceSwitcher'

const EMPTY_DRAFT: PromptDraft = { role: null, task: null, guardrails: null, tone: null }

export function Studio() {
  const { token, activeWorkspace, logout } = useAuth()
  const tid = activeWorkspace?.id
  const canConfigure = can(activeWorkspace?.role, 'triage:configure')
  const canPublish = can(activeWorkspace?.role, 'prompt:publish')

  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCat, setSelectedCat] = useState<string | null>(null)
  const [examples, setExamples] = useState<TriageExample[]>([])
  const [draft, setDraft] = useState<PromptDraft>(EMPTY_DRAFT)
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [versions, setVersions] = useState<PromptVersion[]>([])
  const [error, setError] = useState('')

  // create-category form
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // add-example form
  const [exKind, setExKind] = useState('positive')
  const [exSubject, setExSubject] = useState('')
  const [exBody, setExBody] = useState('')
  const [exReply, setExReply] = useState('')

  const activeVersion = versions.find((v) => v.is_active) ?? null

  const fail = (err: unknown, fallback: string) =>
    setError(err instanceof ApiError ? err.detail : fallback)

  const loadAll = useCallback(async () => {
    if (!token || !tid) return
    try {
      const [cats, vers, dft] = await Promise.all([
        api.listCategories(token, tid),
        api.listVersions(token, tid),
        api.getDraft(token, tid),
      ])
      setCategories(cats)
      setVersions(vers)
      setDraft(dft)
      setError('')
    } catch (err) {
      fail(err, 'Failed to load Studio')
    }
  }, [token, tid])

  // Inline load on mount/workspace change — setState lives in async callbacks
  // (guarded by `active`), never synchronously in the effect body.
  useEffect(() => {
    if (!token || !tid) return
    let active = true
    Promise.all([
      api.listCategories(token, tid),
      api.listVersions(token, tid),
      api.getDraft(token, tid),
    ])
      .then(([cats, vers, dft]) => {
        if (!active) return
        setCategories(cats)
        setVersions(vers)
        setDraft(dft)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.detail : 'Failed to load Studio')
      })
    return () => {
      active = false
    }
  }, [token, tid])

  async function loadExamples(cid: string) {
    if (!token || !tid) return
    setSelectedCat(cid)
    try {
      setExamples(await api.listExamples(token, tid, cid))
    } catch (err) {
      fail(err, 'Failed to load examples')
    }
  }

  async function onCreateCategory(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !tid) return
    try {
      await api.createCategory(token, tid, slug, name, description)
      setSlug('')
      setName('')
      setDescription('')
      await loadAll()
    } catch (err) {
      fail(err, 'Could not create category')
    }
  }

  async function onPatchCategory(cid: string, patch: Partial<Category>) {
    if (!token || !tid) return
    try {
      await api.updateCategory(token, tid, cid, patch)
      await loadAll()
    } catch (err) {
      fail(err, 'Could not update category')
    }
  }

  async function onDeleteCategory(cid: string) {
    if (!token || !tid) return
    if (!confirm('Delete this category?')) return
    try {
      await api.deleteCategory(token, tid, cid)
      if (selectedCat === cid) {
        setSelectedCat(null)
        setExamples([])
      }
      await loadAll()
    } catch (err) {
      fail(err, 'Could not delete category')
    }
  }

  async function onAddExample(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !tid || !selectedCat) return
    try {
      await api.addExample(token, tid, selectedCat, {
        kind: exKind,
        subject: exSubject,
        body: exBody,
        expected_reply: exReply || null,
      })
      setExSubject('')
      setExBody('')
      setExReply('')
      await loadExamples(selectedCat)
    } catch (err) {
      fail(err, 'Could not add example')
    }
  }

  async function onDeleteExample(eid: string) {
    if (!token || !tid || !selectedCat) return
    try {
      await api.deleteExample(token, tid, eid)
      await loadExamples(selectedCat)
    } catch (err) {
      fail(err, 'Could not delete example')
    }
  }

  async function onSaveDraft() {
    if (!token || !tid) return
    try {
      await api.saveDraft(token, tid, draft)
      setError('')
    } catch (err) {
      fail(err, 'Could not save draft')
    }
  }

  async function onPreview() {
    if (!token || !tid) return
    try {
      setPreview(await api.previewPrompt(token, tid))
      setError('')
    } catch (err) {
      fail(err, 'Could not compile preview')
    }
  }

  async function onPublish() {
    if (!token || !tid) return
    try {
      await api.publishPrompt(token, tid)
      await loadAll()
    } catch (err) {
      fail(err, 'Could not publish')
    }
  }

  async function onActivate(version: number) {
    if (!token || !tid) return
    try {
      await api.activateVersion(token, tid, version)
      await loadAll()
    } catch (err) {
      fail(err, 'Could not activate version')
    }
  }

  const card = 'bg-white rounded-2xl border border-gray-200 p-6 space-y-4'
  const input = 'border border-gray-300 rounded-lg px-3 py-2 text-sm w-full'
  const btn = 'bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm'

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <span className="font-semibold text-gray-900">Email Triage</span>
        <div className="flex items-center gap-4 text-sm">
          <WorkspaceSwitcher />
          <Link to="/dashboard" className="text-gray-600 hover:text-gray-900">
            Dashboard
          </Link>
          <Link to="/workspace" className="text-gray-600 hover:text-gray-900">
            Workspace
          </Link>
          <button onClick={logout} className="text-gray-600 hover:text-gray-900">
            Logout
          </button>
        </div>
      </nav>

      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Triage Studio</h1>
          <p className="text-sm text-gray-500">
            Configure this workspace's categories, few-shot examples and prompt.
          </p>
        </div>

        {activeVersion && (
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            A published prompt (v{activeVersion.version}) is live. Edits below take effect on{' '}
            <code>/triage</code> only after you publish again.
          </p>
        )}

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        {/* Categories */}
        <div className={card}>
          <h2 className="text-base font-semibold text-gray-900">Categories</h2>
          <table className="w-full text-sm">
            <tbody>
              {categories.map((c) => (
                <tr key={c.id} className="border-t border-gray-100 align-top">
                  <td className="py-2 pr-2 w-28">
                    <code className="text-xs text-gray-500">{c.slug}</code>
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      defaultValue={c.name}
                      disabled={!canConfigure}
                      onBlur={(e) =>
                        e.target.value !== c.name && onPatchCategory(c.id, { name: e.target.value })
                      }
                      className="border border-gray-200 rounded px-2 py-1 text-sm w-full mb-1"
                    />
                    <input
                      defaultValue={c.description}
                      disabled={!canConfigure}
                      onBlur={(e) =>
                        e.target.value !== c.description &&
                        onPatchCategory(c.id, { description: e.target.value })
                      }
                      className="border border-gray-200 rounded px-2 py-1 text-xs w-full text-gray-600"
                    />
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <label className="text-xs text-gray-500 mr-2">
                      <input
                        type="checkbox"
                        checked={c.is_active}
                        disabled={!canConfigure}
                        onChange={(e) => onPatchCategory(c.id, { is_active: e.target.checked })}
                        className="mr-1 align-middle"
                      />
                      active
                    </label>
                    {canConfigure && (
                      <button
                        onClick={() => onDeleteCategory(c.id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {canConfigure && (
            <form onSubmit={onCreateCategory} className="flex flex-wrap gap-2 pt-2">
              <input
                required
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="slug"
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-32"
              />
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Name"
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-40"
              />
              <input
                required
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description"
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-40"
              />
              <button className={btn}>Add</button>
            </form>
          )}
        </div>

        {/* Examples */}
        <div className={card}>
          <h2 className="text-base font-semibold text-gray-900">Few-shot examples</h2>
          <select
            value={selectedCat ?? ''}
            onChange={(e) => e.target.value && loadExamples(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select a category…</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.slug})
              </option>
            ))}
          </select>

          {selectedCat && (
            <>
              <ul className="space-y-2">
                {examples.map((ex) => (
                  <li key={ex.id} className="border border-gray-100 rounded-lg p-3 text-sm">
                    <div className="flex justify-between">
                      <span className="text-xs font-medium text-gray-500">{ex.kind}</span>
                      {canConfigure && (
                        <button
                          onClick={() => onDeleteExample(ex.id)}
                          className="text-xs text-red-600 hover:underline"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                    <div className="text-gray-900">{ex.subject}</div>
                    <div className="text-gray-500 text-xs">{ex.body}</div>
                    {ex.expected_reply && (
                      <div className="text-gray-400 text-xs mt-1">↳ {ex.expected_reply}</div>
                    )}
                  </li>
                ))}
                {examples.length === 0 && (
                  <li className="text-sm text-gray-400">No examples yet.</li>
                )}
              </ul>

              {canConfigure && (
                <form onSubmit={onAddExample} className="space-y-2 pt-2">
                  <div className="flex gap-2">
                    <select
                      value={exKind}
                      onChange={(e) => setExKind(e.target.value)}
                      className="border border-gray-300 rounded-lg px-2 text-sm"
                    >
                      <option value="positive">positive</option>
                      <option value="negative">negative</option>
                    </select>
                    <input
                      required
                      value={exSubject}
                      onChange={(e) => setExSubject(e.target.value)}
                      placeholder="Subject"
                      className={input}
                    />
                  </div>
                  <textarea
                    required
                    value={exBody}
                    onChange={(e) => setExBody(e.target.value)}
                    placeholder="Email body"
                    className={input}
                    rows={2}
                  />
                  <input
                    value={exReply}
                    onChange={(e) => setExReply(e.target.value)}
                    placeholder="Expected reply (optional)"
                    className={input}
                  />
                  <button className={btn}>Add example</button>
                </form>
              )}
            </>
          )}
        </div>

        {/* Prompt draft + preview */}
        <div className={card}>
          <h2 className="text-base font-semibold text-gray-900">Prompt template</h2>
          <p className="text-xs text-gray-500">Leave a block empty to use the built-in default.</p>
          {(['role', 'task', 'guardrails', 'tone'] as const).map((field) => (
            <div key={field}>
              <label className="text-xs font-medium text-gray-500 capitalize">{field}</label>
              <textarea
                value={draft[field] ?? ''}
                disabled={!canConfigure}
                onChange={(e) => setDraft({ ...draft, [field]: e.target.value || null })}
                className={input}
                rows={field === 'task' || field === 'guardrails' ? 3 : 2}
              />
            </div>
          ))}
          <div className="flex gap-2">
            {canConfigure && (
              <button onClick={onSaveDraft} className={btn}>
                Save draft
              </button>
            )}
            <button
              onClick={onPreview}
              className="border border-gray-300 rounded-lg px-4 py-2 text-sm hover:bg-gray-50"
            >
              Preview compiled prompt
            </button>
          </div>
          {preview && (
            <div>
              <p className="text-xs text-gray-500 mb-1">
                allowed slugs: {preview.allowed_slugs.join(', ')}
              </p>
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto whitespace-pre-wrap">
                {preview.prompt}
              </pre>
            </div>
          )}
        </div>

        {/* Versions */}
        <div className={card}>
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">Published versions</h2>
            {canPublish && (
              <button onClick={onPublish} className={btn}>
                Publish current draft
              </button>
            )}
          </div>
          {versions.length === 0 ? (
            <p className="text-sm text-gray-400">
              Not published yet — <code>/triage</code> compiles the draft live.
            </p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id} className="border-t border-gray-100">
                    <td className="py-2">
                      v{v.version}
                      {v.is_active && (
                        <span className="ml-2 text-xs text-green-700 bg-green-50 rounded px-1.5 py-0.5">
                          active
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-xs text-gray-500">
                      {v.accuracy != null ? `acc ${v.accuracy.toFixed(2)}` : '—'}
                      {v.macro_f1 != null ? ` · f1 ${v.macro_f1.toFixed(2)}` : ''}
                    </td>
                    <td className="py-2 text-right">
                      {canPublish && !v.is_active && (
                        <button
                          onClick={() => onActivate(v.version)}
                          className="text-xs text-indigo-600 hover:underline"
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
