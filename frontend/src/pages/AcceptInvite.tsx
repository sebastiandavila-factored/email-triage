import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'

function readInviteToken(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get('token')
}

export function AcceptInvite() {
  const { token, refreshWorkspaces, setActiveWorkspace } = useAuth()
  const navigate = useNavigate()
  const [inviteToken] = useState(readInviteToken)
  const [status, setStatus] = useState<'working' | 'done' | 'error'>(
    inviteToken ? 'working' : 'error',
  )
  const [message, setMessage] = useState(
    inviteToken ? 'Joining workspace…' : 'No invitation token in the link.',
  )
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current || !token || !inviteToken) return
    ran.current = true
    window.history.replaceState(null, '', window.location.pathname)

    api
      .acceptInvite(token, inviteToken)
      .then(async (res) => {
        await refreshWorkspaces()
        setActiveWorkspace(res.tenant_id)
        setStatus('done')
        setMessage(`Joined "${res.tenant_name}" as ${res.role}.`)
        setTimeout(() => navigate('/workspace'), 1200)
      })
      .catch((err) => {
        setStatus('error')
        setMessage(err instanceof ApiError ? err.detail : 'Could not accept invitation')
      })
  }, [token, inviteToken, refreshWorkspaces, setActiveWorkspace, navigate])

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-gray-200 p-8 text-center">
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Workspace invitation</h1>
        <p className={status === 'error' ? 'text-sm text-red-600' : 'text-sm text-gray-600'}>
          {message}
        </p>
        {status === 'error' && (
          <button
            onClick={() => navigate('/dashboard')}
            className="mt-4 text-sm text-indigo-600 hover:underline"
          >
            Go to dashboard
          </button>
        )}
      </div>
    </div>
  )
}
