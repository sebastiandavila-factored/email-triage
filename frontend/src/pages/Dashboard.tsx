import { useState } from 'react'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { TriageResponse } from '../api'
import { TraceChat } from '../components/TraceChat'
import { AppShell } from '../components/ui/AppShell'
import { Button, Card, Field, SectionHead, Tag } from '../components/ui/kit'
import { can } from '../rbac'

export function Dashboard() {
  const { user, token, apiKey } = useAuth()
  const [subject, setSubject] = useState('')
  const [sender, setSender] = useState('')
  const [body, setBody] = useState('')
  const [result, setResult] = useState<TriageResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showTraces, setShowTraces] = useState(false)

  async function handleTriage(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    if (!apiKey) {
      setError('API key not set. Go to Settings to enter or rotate your API key.')
      return
    }
    setError('')
    setResult(null)
    setShowTraces(false)
    setLoading(true)
    try {
      const data = await api.triage(token, apiKey, subject, sender, body)
      setResult(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Hello, {user?.display_name} 👋</h1>
          <p className="text-sm text-muted mt-1">
            Workspace: <span className="font-medium text-ink-soft">{user?.tenant_name}</span> ·
            role: <span className="font-medium text-ink-soft">{user?.role}</span>
          </p>
        </div>

        {/* Triage form */}
        <Card className="p-6">
          <SectionHead kicker="Classify + draft" title="Triage an email" className="mb-4" />
          <form onSubmit={handleTriage} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Subject"
                required
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Order status inquiry"
              />
              <Field
                label="From"
                required
                value={sender}
                onChange={(e) => setSender(e.target.value)}
                placeholder="customer@example.com"
              />
            </div>
            <label className="block">
              <span className="block text-sm font-medium text-ink-soft mb-1">Body</span>
              <textarea
                required
                rows={5}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full bg-paper border border-line rounded-lg px-3 py-2 text-sm text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-brand resize-none"
                placeholder="Paste the email body here…"
              />
            </label>

            {error && (
              <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
            )}

            <Button type="submit" disabled={loading} className="w-full">
              {loading ? 'Analyzing…' : 'Triage email →'}
            </Button>
          </form>
        </Card>

        {/* Result */}
        {result && (
          <Card className="p-6 space-y-4">
            <SectionHead
              kicker="Result"
              title={<Tag tone="amber">{result.category}</Tag>}
              actions={
                <span className="text-xs text-muted">
                  Confidence: {(result.confidence * 100).toFixed(0)}%
                </span>
              }
            />
            <div>
              <p className="font-mono text-[11px] uppercase tracking-wide text-faint mb-2">
                Draft reply
              </p>
              <div className="bg-ground rounded-lg p-4 text-sm text-ink-soft leading-relaxed border border-line">
                {result.draft_reply}
              </div>
              <button
                onClick={() => navigator.clipboard.writeText(result.draft_reply)}
                className="mt-2 text-xs text-brand hover:underline"
              >
                Copy reply
              </button>
            </div>

            {/* Trace-debug chat — owner/admin only, and only once we have a trace id */}
            {can(user?.role, 'traces:read') && result.trace_id && token && user?.tenant_id && (
              <div>
                <button
                  onClick={() => setShowTraces((v) => !v)}
                  className="text-xs text-muted hover:text-ink transition"
                >
                  {showTraces ? '▾ Hide traces' : '▸ Ver traces'}
                </button>
                {showTraces && (
                  <TraceChat token={token} tid={user.tenant_id} traceId={result.trace_id} />
                )}
              </div>
            )}
          </Card>
        )}
      </div>
    </AppShell>
  )
}
