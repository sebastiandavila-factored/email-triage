import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { nextAfterAuth } from '../invite'

export function Signup() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await signup(email, password, displayName)
      setApiKey(result.api_key)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
      setLoading(false)
    }
  }

  if (apiKey) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
          <div className="text-center mb-4">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-green-100 mb-3">
              <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900">Account created!</h2>
            <p className="text-sm text-gray-500 mt-1">Save your API key — it won't be shown again.</p>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
            <p className="text-xs font-medium text-amber-800 mb-1">API Key</p>
            <code className="text-xs text-amber-900 break-all">{apiKey}</code>
          </div>

          <button
            onClick={() => {
              navigator.clipboard.writeText(apiKey)
            }}
            className="w-full border border-gray-300 rounded-lg py-2 text-sm text-gray-700 hover:bg-gray-50 transition mb-3"
          >
            Copy API key
          </button>

          <button
            onClick={() => navigate(nextAfterAuth())}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg py-2.5 text-sm transition"
          >
            Continue →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">Create account</h1>
        <p className="text-sm text-gray-500 mb-6">Email Triage — AI support assistant</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Display name</label>
            <input
              type="text"
              required
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="Alice"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="you@company.com"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="8+ characters"
            />
          </div>

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg py-2.5 text-sm transition"
          >
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500 mt-6">
          Already have an account?{' '}
          <Link to="/login" className="text-indigo-600 hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
