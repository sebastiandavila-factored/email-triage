import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { nextAfterAuth } from '../invite'
import { AuthLayout } from '../components/ui/AuthLayout'
import { Button, Field } from '../components/ui/kit'

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
      <AuthLayout>
        <div className="text-center mb-4">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-brand-wash mb-3">
            <svg className="w-6 h-6 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-ink">Account created!</h2>
          <p className="text-sm text-muted mt-1">Save your API key — it won't be shown again.</p>
        </div>

        <div className="bg-amber-wash border border-line rounded-lg p-3 mb-4">
          <p className="font-mono text-[11px] uppercase tracking-wide text-amber mb-1">API Key</p>
          <code className="text-xs text-ink break-all">{apiKey}</code>
        </div>

        <Button
          variant="ghost"
          onClick={() => navigator.clipboard.writeText(apiKey)}
          className="w-full mb-3"
        >
          Copy API key
        </Button>
        <Button onClick={() => navigate(nextAfterAuth())} className="w-full">
          Continue →
        </Button>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Create account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field
          label="Display name"
          type="text"
          required
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Alice"
        />
        <Field
          label="Email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
        />
        <Field
          label="Password"
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="8+ characters"
        />

        {error && (
          <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
        )}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Creating account…' : 'Create account'}
        </Button>
      </form>

      <p className="text-center text-sm text-muted mt-6">
        Already have an account?{' '}
        <Link to="/login" className="text-brand hover:underline font-medium">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
