import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { TriageResponse } from '../api'

const CATEGORY_COLORS: Record<string, string> = {
  status: 'bg-blue-100 text-blue-800',
  refunds: 'bg-red-100 text-red-800',
  availability: 'bg-green-100 text-green-800',
  shipments: 'bg-orange-100 text-orange-800',
  prices: 'bg-purple-100 text-purple-800',
}

export function Dashboard() {
  const { user, token, apiKey, logout } = useAuth()
  const [subject, setSubject] = useState('')
  const [sender, setSender] = useState('')
  const [body, setBody] = useState('')
  const [result, setResult] = useState<TriageResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleTriage(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    if (!apiKey) {
      setError('API key not set. Go to Settings to enter or rotate your API key.')
      return
    }
    setError('')
    setResult(null)
    setLoading(true)
    try {
      const data = await api.triage(token, apiKey, subject, sender, body)
      setResult(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Navbar */}
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <span className="font-semibold text-gray-900">Email Triage</span>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-gray-500">{user?.email}</span>
          <Link to="/settings" className="text-gray-600 hover:text-gray-900">
            Settings
          </Link>
          <button onClick={logout} className="text-gray-600 hover:text-gray-900">
            Logout
          </button>
        </div>
      </nav>

      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Hello, {user?.display_name} 👋
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Workspace: <span className="font-medium">{user?.tenant_name}</span> · role:{' '}
            <span className="font-medium">{user?.role}</span>
          </p>
        </div>

        {/* Triage form */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Triage an email</h2>
          <form onSubmit={handleTriage} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subject</label>
                <input
                  type="text"
                  required
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="Order status inquiry"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
                <input
                  type="text"
                  required
                  value={sender}
                  onChange={(e) => setSender(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="customer@example.com"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Body</label>
              <textarea
                required
                rows={5}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                placeholder="Paste the email body here…"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg py-2.5 text-sm transition"
            >
              {loading ? 'Analyzing…' : 'Triage email →'}
            </button>
          </form>
        </div>

        {/* Result */}
        {result && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">Result</h2>
              <span className="text-xs text-gray-500">
                Confidence: {(result.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide ${CATEGORY_COLORS[result.category] ?? 'bg-gray-100 text-gray-800'}`}
              >
                {result.category}
              </span>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Draft reply</p>
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 leading-relaxed">
                {result.draft_reply}
              </div>
              <button
                onClick={() => navigator.clipboard.writeText(result.draft_reply)}
                className="mt-2 text-xs text-indigo-600 hover:underline"
              >
                Copy reply
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
