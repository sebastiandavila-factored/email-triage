import type { ReactNode } from 'react'
import { Card } from './kit'
import { ThemeToggle } from './ThemeToggle'

// Centered auth card (Login / Signup / AcceptInvite) in the Triage Studio look (Plan 34).
export function AuthLayout({
  title,
  children,
}: {
  title?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-ground text-ink flex items-center justify-center px-4 relative">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 justify-center mb-1 font-semibold text-ink">
          <span className="font-mono text-brand">&lt;/&gt;</span>
          Triage Studio
        </div>
        <p className="text-sm text-muted text-center mb-6">AI support triage &amp; drafts</p>
        <Card className="p-6">
          {title && <h1 className="text-lg font-semibold text-ink mb-4">{title}</h1>}
          {children}
        </Card>
      </div>
    </div>
  )
}
