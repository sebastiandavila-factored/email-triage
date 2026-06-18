// Typed fetch wrappers for the email-triage API.
// Dev: VITE_API_URL is unset → API_BASE is '' → relative paths hit the Vite
// proxy (same-origin). Prod: VITE_API_URL = https://<api>.onrender.com, baked
// in at build time, so the SPA calls the Render API cross-origin (needs CORS).
export const API_BASE = import.meta.env.VITE_API_URL ?? ''

export interface AuthUser {
  user_id: string
  email: string
  display_name: string
  email_verified: boolean
  tenant_id: string
  tenant_name: string
  tenant_type: string
  plan: string
  role: string
}

export interface SignupResponse {
  access_token: string
  token_type: string
  email: string
  display_name: string
  tenant_id: string
  tenant_name: string
  tenant_type: string
  plan: string
  api_key: string
  message: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  email: string
  display_name: string
  tenant_id: string
  tenant_name: string
  tenant_type: string
  plan: string
  role: string
  message: string
}

export interface TriageResponse {
  category: string
  draft_reply: string
  confidence: number
}

export interface RotateKeyResponse {
  api_key: string
  message: string
}

export interface Workspace {
  id: string
  name: string
  type: string
  plan: string
  role: string
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: string
}

export interface Invitation {
  id: string
  email: string
  role: string
  status: string
  expires_at: string
}

export interface CreateInviteResponse {
  invitation_id: string
  email: string
  role: string
  link: string
  message: string
}

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  signup(email: string, password: string, display_name: string): Promise<SignupResponse> {
    return request('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name }),
    })
  },

  login(email: string, password: string): Promise<LoginResponse> {
    return request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },

  me(token: string): Promise<AuthUser> {
    return request('/auth/me', {}, token)
  },

  logout(token: string): Promise<{ message: string }> {
    return request('/auth/logout', { method: 'POST' }, token)
  },

  triage(token: string, apiKey: string, subject: string, sender: string, body: string): Promise<TriageResponse> {
    return request(
      '/triage',
      {
        method: 'POST',
        body: JSON.stringify({ subject, sender, body }),
        headers: { 'X-Api-Key': apiKey },
      },
      token,
    )
  },

  rotateKey(token: string): Promise<RotateKeyResponse> {
    return request('/auth/rotate-key', { method: 'POST' }, token)
  },

  // ── Workspaces ──────────────────────────────────────────────────────────────

  listWorkspaces(token: string): Promise<Workspace[]> {
    return request('/workspaces', {}, token)
  },

  createWorkspace(token: string, name: string): Promise<Workspace> {
    return request('/workspaces', { method: 'POST', body: JSON.stringify({ name }) }, token)
  },

  deleteWorkspace(token: string, tid: string): Promise<void> {
    return request(`/workspaces/${tid}`, { method: 'DELETE' }, token)
  },

  getMembers(token: string, tid: string): Promise<Member[]> {
    return request(`/workspaces/${tid}/members`, {}, token)
  },

  changeRole(token: string, tid: string, uid: string, role: string): Promise<Member> {
    return request(
      `/workspaces/${tid}/members/${uid}`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
      token,
    )
  },

  removeMember(token: string, tid: string, uid: string): Promise<void> {
    return request(`/workspaces/${tid}/members/${uid}`, { method: 'DELETE' }, token)
  },

  createInvite(token: string, tid: string, email: string, role: string): Promise<CreateInviteResponse> {
    return request(
      `/workspaces/${tid}/invitations`,
      { method: 'POST', body: JSON.stringify({ email, role }) },
      token,
    )
  },

  listInvites(token: string, tid: string): Promise<Invitation[]> {
    return request(`/workspaces/${tid}/invitations`, {}, token)
  },

  revokeInvite(token: string, tid: string, id: string): Promise<void> {
    return request(`/workspaces/${tid}/invitations/${id}`, { method: 'DELETE' }, token)
  },

  acceptInvite(token: string, inviteToken: string): Promise<{ tenant_id: string; tenant_name: string; role: string }> {
    return request('/invitations/accept', { method: 'POST', body: JSON.stringify({ token: inviteToken }) }, token)
  },
}
