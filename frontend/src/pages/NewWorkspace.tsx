import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'

export function NewWorkspace() {
  const { token, refreshWorkspaces, setActiveWorkspace } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    setError('')
    setLoading(true)
    try {
      const ws = await api.createWorkspace(token, name)
      await refreshWorkspaces()
      setActiveWorkspace(ws.id)
      navigate('/workspace')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not create workspace')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-ground flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-paper rounded-2xl shadow-sm border border-line p-8">
        <h1 className="text-2xl font-semibold text-ink mb-1">New team workspace</h1>
        <p className="text-sm text-muted mb-6">You'll be the owner. Invite members afterwards.</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Support"
            className="w-full border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
          />
          {error && <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-brand hover:bg-brand-bright disabled:opacity-50 text-paper font-medium rounded-lg py-2.5 text-sm"
          >
            {loading ? 'Creating…' : 'Create workspace'}
          </button>
        </form>
        <p className="text-center text-sm text-muted mt-6">
          <Link to="/workspace" className="text-brand hover:underline">
            Back
          </Link>
        </p>
      </div>
    </div>
  )
}
