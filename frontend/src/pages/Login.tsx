import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { API_BASE } from '../api'
import { nextAfterAuth } from '../invite'
import { AuthLayout } from '../components/ui/AuthLayout'
import { Button, Field } from '../components/ui/kit'

export function Login() {
  const { login, token } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Already authenticated (e.g. just returned from Google SSO) → go straight in,
  // honouring a pending invite if there is one.
  if (token) return <Navigate to={nextAfterAuth()} replace />

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate(nextAfterAuth())
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Sign in">
      {/* Google SSO */}
      <a
        href={`${API_BASE}/auth/login`}
        className="flex items-center justify-center gap-3 w-full border border-line rounded-lg py-2.5 text-sm font-medium text-ink hover:bg-brand-wash hover:border-line-strong transition mb-4"
      >
        <GoogleIcon />
        Continue with Google
      </a>

      <div className="relative my-4">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-line" />
        </div>
        <div className="relative flex justify-center text-xs text-faint bg-paper px-2">or</div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
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
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />

        {error && (
          <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
        )}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>

      <p className="text-center text-sm text-muted mt-6">
        No account?{' '}
        <Link to="/signup" className="text-brand hover:underline font-medium">
          Sign up
        </Link>
      </p>
    </AuthLayout>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" />
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 6.29C4.672 4.163 6.656 3.58 9 3.58z" />
    </svg>
  )
}
