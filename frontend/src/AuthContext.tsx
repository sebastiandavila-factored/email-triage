import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError } from './api'
import type { AuthUser } from './api'

const TOKEN_KEY = 'access_token'
const API_KEY_KEY = 'api_key'

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  apiKey: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string, displayName: string) => Promise<{ api_key: string }>
  logout: () => void
  setApiKey: (key: string) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Resolve the token before the first render so ProtectedRoute never sees a
// transient null right after the Google SSO redirect (which would bounce the
// user to /login). Order: stored token, else the #token=<jwt> fragment.
function readBootstrapToken(): string | null {
  const stored = localStorage.getItem(TOKEN_KEY)
  if (stored) return stored
  const hash = window.location.hash
  if (hash.includes('token=')) {
    const fragmentToken = new URLSearchParams(hash.slice(1)).get('token')
    if (fragmentToken) {
      localStorage.setItem(TOKEN_KEY, fragmentToken)
      return fragmentToken
    }
  }
  return null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(readBootstrapToken)
  const [apiKey, setApiKeyState] = useState<string | null>(() => localStorage.getItem(API_KEY_KEY))
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // The token was already captured above; just scrub it from the URL bar.
  useEffect(() => {
    if (window.location.hash.includes('token=')) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])

  // Validate stored token on mount by calling /auth/me
  useEffect(() => {
    if (!token) {
      setIsLoading(false)
      return
    }
    api
      .me(token)
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
      })
      .finally(() => setIsLoading(false))
  }, [token])

  async function login(email: string, password: string) {
    const data = await api.login(email, password)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    const me = await api.me(data.access_token)
    setUser(me)
  }

  async function signup(email: string, password: string, displayName: string) {
    const data = await api.signup(email, password, displayName)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    // Persist the freshly-issued API key so /triage works without a manual
    // re-entry in Settings (it is only ever returned once, here).
    localStorage.setItem(API_KEY_KEY, data.api_key)
    setApiKeyState(data.api_key)
    const me = await api.me(data.access_token)
    setUser(me)
    return { api_key: data.api_key }
  }

  function logout() {
    if (token) api.logout(token).catch(() => {})
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  function setApiKey(key: string) {
    localStorage.setItem(API_KEY_KEY, key)
    setApiKeyState(key)
  }

  return (
    <AuthContext.Provider value={{ user, token, apiKey, isLoading, login, signup, logout, setApiKey }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

export function useRequireAuth() {
  const auth = useAuth()
  if (!auth.isLoading && !auth.token) {
    window.location.href = '/login'
  }
  return auth
}

// Helper: raise ApiError — re-exported for pages to use
export { ApiError }
