import { Link, NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../../AuthContext'
import { WorkspaceSwitcher } from '../WorkspaceSwitcher'
import { ThemeToggle } from './ThemeToggle'

// The shared authenticated shell (Plan 34): one navbar for every page, replacing the copy
// pasted into Dashboard/Studio/Settings/Workspace/Compare. Brand is "Triage Studio".

function Brand() {
  return (
    <Link to="/dashboard" className="flex items-center gap-2 font-semibold text-ink">
      <span className="font-mono text-brand">&lt;/&gt;</span>
      Triage Studio
    </Link>
  )
}

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? 'text-ink font-medium' : 'text-muted hover:text-ink transition'
}

export function AppShell({ children }: { children: ReactNode }) {
  const { logout } = useAuth()
  return (
    <div className="min-h-screen bg-ground text-ink">
      <nav className="bg-paper border-b border-line px-6 py-3 flex items-center justify-between">
        <Brand />
        <div className="flex items-center gap-4 text-sm">
          <WorkspaceSwitcher />
          <NavLink to="/inbox" className={navClass}>
            Inbox
          </NavLink>
          <NavLink to="/compare" className={navClass}>
            Compare
          </NavLink>
          <NavLink to="/workspace" className={navClass}>
            Workspace
          </NavLink>
          <NavLink to="/studio" className={navClass}>
            Studio
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            Settings
          </NavLink>
          <ThemeToggle />
          <button onClick={logout} className="text-muted hover:text-ink transition">
            Logout
          </button>
        </div>
      </nav>
      <main>{children}</main>
    </div>
  )
}
