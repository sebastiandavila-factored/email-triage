import { useState } from 'react'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import { AppShell } from '../components/ui/AppShell'

export function Settings() {
  const { user, token, apiKey, setApiKey } = useAuth()
  const [rotated, setRotated] = useState('')
  const [manualKey, setManualKey] = useState(apiKey ?? '')
  const [error, setError] = useState('')
  const [rotating, setRotating] = useState(false)

  async function handleRotate() {
    if (!token) return
    setError('')
    setRotating(true)
    try {
      const data = await api.rotateKey(token)
      setRotated(data.api_key)
      setApiKey(data.api_key)
      setManualKey(data.api_key)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
    } finally {
      setRotating(false)
    }
  }

  function handleSaveManualKey(e: React.FormEvent) {
    e.preventDefault()
    setApiKey(manualKey.trim())
  }

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <h1 className="text-2xl font-semibold text-ink">Settings</h1>

        {/* Workspace info */}
        <div className="bg-paper rounded-2xl border border-line p-6">
          <h2 className="text-base font-semibold text-ink mb-4">Workspace</h2>
          <dl className="space-y-3 text-sm">
            {[
              ['Name', user?.tenant_name],
              ['Type', user?.tenant_type],
              ['Plan', user?.plan],
              ['Your role', user?.role],
              ['Email', user?.email],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between">
                <dt className="text-muted">{label}</dt>
                <dd className="font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Active API key */}
        <div className="bg-paper rounded-2xl border border-line p-6">
          <h2 className="text-base font-semibold text-ink mb-1">API key in use</h2>
          <p className="text-xs text-muted mb-4">
            This key is sent as <code className="bg-ground px-1 rounded">X-Api-Key</code> on every
            triage request.
          </p>
          {apiKey ? (
            <div className="bg-ground rounded-lg p-3 font-mono text-xs text-ink-soft break-all">
              {apiKey.slice(0, 8)}•••••••••••••••••••••••••
            </div>
          ) : (
            <p className="text-sm text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
              No API key saved. Enter one below or rotate to generate a new one.
            </p>
          )}
        </div>

        {/* Enter key manually */}
        <div className="bg-paper rounded-2xl border border-line p-6">
          <h2 className="text-base font-semibold text-ink mb-4">Set API key manually</h2>
          <form onSubmit={handleSaveManualKey} className="flex gap-2">
            <input
              type="text"
              value={manualKey}
              onChange={(e) => setManualKey(e.target.value)}
              className="flex-1 border border-line rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand"
              placeholder="Paste your API key here"
            />
            <button
              type="submit"
              className="bg-brand hover:bg-brand-bright text-paper text-sm font-medium rounded-lg px-4 py-2 transition"
            >
              Save
            </button>
          </form>
        </div>

        {/* Rotate key */}
        <div className="bg-paper rounded-2xl border border-line p-6">
          <h2 className="text-base font-semibold text-ink mb-1">Rotate API key</h2>
          <p className="text-xs text-muted mb-4">
            Generates a new key and immediately invalidates the old one.
            {user?.role === 'member' && (
              <span className="text-crit ml-1">Requires owner or admin role.</span>
            )}
          </p>

          {rotated && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
              <p className="text-xs font-medium text-amber-800 mb-1">New API Key — save it now</p>
              <code className="text-xs text-amber-900 break-all">{rotated}</code>
              <button
                onClick={() => navigator.clipboard.writeText(rotated)}
                className="mt-2 block text-xs text-amber-700 hover:underline"
              >
                Copy
              </button>
            </div>
          )}

          {error && (
            <p className="text-sm text-crit border border-line rounded-lg px-3 py-2 mb-4">{error}</p>
          )}

          <button
            onClick={handleRotate}
            disabled={rotating}
            className="bg-crit hover:opacity-90 disabled:opacity-50 text-paper text-sm font-medium rounded-lg px-4 py-2 transition"
          >
            {rotating ? 'Rotating…' : 'Rotate key'}
          </button>
        </div>
      </div>
    </AppShell>
  )
}
