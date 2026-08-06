import { useAuth } from '../AuthContext'

export function WorkspaceSwitcher() {
  const { workspaces, activeWorkspace, setActiveWorkspace } = useAuth()
  if (workspaces.length === 0) return null
  return (
    <select
      value={activeWorkspace?.id ?? ''}
      onChange={(e) => setActiveWorkspace(e.target.value)}
      className="border border-line rounded-lg px-2 py-1 text-sm text-ink bg-paper focus:outline-none focus:ring-2 focus:ring-brand"
      aria-label="Active workspace"
    >
      {workspaces.map((w) => (
        <option key={w.id} value={w.id}>
          {w.name} · {w.role}
        </option>
      ))}
    </select>
  )
}
