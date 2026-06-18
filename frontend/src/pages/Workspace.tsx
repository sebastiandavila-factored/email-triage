import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { Member, Invitation } from '../api'
import { can } from '../rbac'
import { WorkspaceSwitcher } from '../components/WorkspaceSwitcher'

const ROLES = ['member', 'admin', 'owner']

export function Workspace() {
  const { token, user, activeWorkspace, refreshWorkspaces, logout } = useAuth()
  const navigate = useNavigate()
  const [members, setMembers] = useState<Member[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [error, setError] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('member')
  const [inviteLink, setInviteLink] = useState('')

  const tid = activeWorkspace?.id
  const manage = can(activeWorkspace?.role, 'workspace:manage')
  const canDelete = can(activeWorkspace?.role, 'workspace:delete') && activeWorkspace?.type === 'team'

  async function load() {
    if (!token || !tid) return
    try {
      const m = await api.getMembers(token, tid)
      const inv = manage ? await api.listInvites(token, tid) : []
      setMembers(m)
      setInvites(inv)
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load workspace')
    }
  }

  useEffect(() => {
    if (!token || !tid) return
    let active = true
    Promise.all([
      api.getMembers(token, tid),
      manage ? api.listInvites(token, tid) : Promise.resolve<Invitation[]>([]),
    ])
      .then(([m, inv]) => {
        if (!active) return
        setMembers(m)
        setInvites(inv)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.detail : 'Failed to load workspace')
      })
    return () => {
      active = false
    }
  }, [token, tid, manage])

  async function onChangeRole(uid: string, role: string) {
    if (!token || !tid) return
    setError('')
    try {
      await api.changeRole(token, tid, uid, role)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not change role')
    }
  }

  async function onRemove(uid: string) {
    if (!token || !tid) return
    setError('')
    try {
      await api.removeMember(token, tid, uid)
      if (uid === user?.user_id) {
        await refreshWorkspaces()
        navigate('/dashboard')
      } else {
        await load()
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not remove member')
    }
  }

  async function onInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !tid) return
    setError('')
    setInviteLink('')
    try {
      const res = await api.createInvite(token, tid, inviteEmail, inviteRole)
      setInviteLink(res.link)
      setInviteEmail('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not create invitation')
    }
  }

  async function onRevoke(id: string) {
    if (!token || !tid) return
    try {
      await api.revokeInvite(token, tid, id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not revoke')
    }
  }

  async function onDeleteWorkspace() {
    if (!token || !tid) return
    if (!confirm('Delete this workspace? This cannot be undone.')) return
    try {
      await api.deleteWorkspace(token, tid)
      await refreshWorkspaces()
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not delete workspace')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <span className="font-semibold text-gray-900">Email Triage</span>
        <div className="flex items-center gap-4 text-sm">
          <WorkspaceSwitcher />
          <Link to="/dashboard" className="text-gray-600 hover:text-gray-900">
            Dashboard
          </Link>
          <button onClick={logout} className="text-gray-600 hover:text-gray-900">
            Logout
          </button>
        </div>
      </nav>

      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-gray-900">{activeWorkspace?.name}</h1>
          <Link
            to="/workspace/new"
            className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-3 py-1.5"
          >
            + New team
          </Link>
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        {/* Members */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Members</h2>
          <table className="w-full text-sm">
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id} className="border-t border-gray-100">
                  <td className="py-2">
                    <div className="text-gray-900">{m.display_name}</div>
                    <div className="text-gray-400 text-xs">{m.email}</div>
                  </td>
                  <td className="py-2 text-right">
                    {manage ? (
                      <select
                        value={m.role}
                        onChange={(e) => onChangeRole(m.user_id, e.target.value)}
                        className="border border-gray-300 rounded px-2 py-1 text-xs"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-gray-600">{m.role}</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {(manage || m.user_id === user?.user_id) && (
                      <button
                        onClick={() => onRemove(m.user_id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        {m.user_id === user?.user_id ? 'Leave' : 'Remove'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Invitations */}
        {manage && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-gray-900">Invite a member</h2>
            <form onSubmit={onInvite} className="flex gap-2">
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="person@company.com"
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="border border-gray-300 rounded-lg px-2 text-sm"
              >
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
              <button className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 text-sm">
                Invite
              </button>
            </form>

            {inviteLink && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                <p className="text-xs font-medium text-amber-800 mb-1">
                  Invitation link (shown once — share it):
                </p>
                <code className="text-xs text-amber-900 break-all">{inviteLink}</code>
                <button
                  onClick={() => navigator.clipboard.writeText(inviteLink)}
                  className="ml-2 text-xs text-indigo-600 hover:underline"
                >
                  Copy
                </button>
              </div>
            )}

            {invites.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">Pending invitations</p>
                <ul className="space-y-1">
                  {invites.map((inv) => (
                    <li key={inv.id} className="flex justify-between text-sm">
                      <span className="text-gray-700">
                        {inv.email} · {inv.role}
                      </span>
                      <button
                        onClick={() => onRevoke(inv.id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Revoke
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {canDelete && (
          <button
            onClick={onDeleteWorkspace}
            className="text-sm text-red-600 border border-red-200 rounded-lg px-3 py-2 hover:bg-red-50"
          >
            Delete this workspace
          </button>
        )}
      </div>
    </div>
  )
}
