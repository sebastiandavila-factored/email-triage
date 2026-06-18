import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError } from './api'
import type { AuthUser, Workspace } from './api'

const TOKEN_KEY = 'access_token'
const API_KEY_KEY = 'api_key'
const ACTIVE_WS_KEY = 'active_workspace_id'

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  apiKey: string | null
  isLoading: boolean
  workspaces: Workspace[]
  activeWorkspace: Workspace | null
  setActiveWorkspace: (id: string) => void
  refreshWorkspaces: () => Promise<void>
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
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeId, setActiveId] = useState<string | null>(() => localStorage.getItem(ACTIVE_WS_KEY))
  // Only "loading" if there is a token to validate; avoids a synchronous
  // setState in the effect for the no-token case.
  const [isLoading, setIsLoading] = useState<boolean>(() => localStorage.getItem(TOKEN_KEY) != null)

  // Personal workspace is the sensible default when none was chosen.
  const activeWorkspace =
    workspaces.find((w) => w.id === activeId) ??
    workspaces.find((w) => w.type === 'personal') ??
    workspaces[0] ??
    null

  // The token was already captured above; just scrub it from the URL bar.
  useEffect(() => {
    if (window.location.hash.includes('token=')) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])

  // Validate stored token on mount. `me` is the source of truth for auth: only
  // its failure logs the user out. Workspaces are best-effort — a failing
  // /workspaces (e.g. backend without that endpoint) must NOT tear down the
  // session and bounce the user back to /login.
  useEffect(() => {
    if (!token) return
    let active = true
    api
      .me(token)
      .then((me) => {
        if (!active) return
        setUser(me)
        return api
          .listWorkspaces(token)
          .then((ws) => {
            if (active) setWorkspaces(ws)
          })
          .catch(() => {})
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
    }
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

  function setActiveWorkspace(id: string) {
    localStorage.setItem(ACTIVE_WS_KEY, id)
    setActiveId(id)
  }

  async function refreshWorkspaces() {
    if (!token) return
    setWorkspaces(await api.listWorkspaces(token).catch(() => []))
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        apiKey,
        isLoading,
        workspaces,
        activeWorkspace,
        setActiveWorkspace,
        refreshWorkspaces,
        login,
        signup,
        logout,
        setApiKey,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its provider
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

// Helper: raise ApiError — re-exported for pages to use
export { ApiError }
