import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { GmailStatus, InboxItem, VoiceReport } from '../api'
import { TraceChat } from '../components/TraceChat'
import { DiagnosePanel } from '../components/TraceDiagnosisView'
import { VoiceScriptView } from '../components/VoiceScriptView'
import { AppShell } from '../components/ui/AppShell'
import { Button, Card, SectionHead, Tag } from '../components/ui/kit'
import { can } from '../rbac'

function timeOf(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function relSync(iso?: string | null): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 'never'
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  return d.toLocaleString()
}

export function Inbox() {
  const { user, token } = useAuth()
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState<GmailStatus | null>(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [items, setItems] = useState<InboxItem[] | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(true)
  const [days, setDays] = useState(1)
  const [error, setError] = useState('')
  const [needsReconnect, setNeedsReconnect] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [report, setReport] = useState<VoiceReport | null>(null)
  const [generating, setGenerating] = useState(false)
  const [reportError, setReportError] = useState('')
  // Read the OAuth callback flag once at mount (?gmail=connected|denied); the effect
  // below only strips it from the URL.
  const [notice] = useState(() => {
    const flag = new URLSearchParams(window.location.search).get('gmail')
    if (flag === 'connected') return 'Gmail connected.'
    if (flag === 'denied') return 'Gmail was not connected.'
    return ''
  })

  const canConnect = can(user?.role, 'gmail:connect')

  // No synchronous setState here (loadingStatus starts true) so it's safe to call
  // from an effect; the first state write happens after the await.
  const loadStatus = useCallback(async () => {
    if (!token) return
    try {
      setStatus(await api.gmailStatus(token))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not load Gmail status')
    } finally {
      setLoadingStatus(false)
    }
  }, [token])

  useEffect(() => {
    if (!token) return
    // setState only inside the promise callbacks (not synchronously in the effect body).
    api
      .gmailStatus(token)
      .then(setStatus)
      .catch((err) => setError(err instanceof ApiError ? err.detail : 'Could not load Gmail status'))
      .finally(() => setLoadingStatus(false))
  }, [token])

  // Strip the one-shot ?gmail flag from the URL after reading it at mount.
  useEffect(() => {
    if (params.get('gmail')) {
      params.delete('gmail')
      setParams(params, { replace: true })
    }
  }, [params, setParams])

  async function handleConnect() {
    if (!token) return
    setError('')
    try {
      const { authorization_url } = await api.gmailConnect(token)
      window.location.assign(authorization_url)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not start Gmail connection')
    }
  }

  async function handleDisconnect() {
    if (!token) return
    setError('')
    try {
      await api.gmailDisconnect(token)
      setItems(null)
      setNeedsReconnect(false)
      await loadStatus()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not disconnect Gmail')
    }
  }

  async function handleSync() {
    if (!token) return
    setError('')
    setNeedsReconnect(false)
    setSyncing(true)
    setReport(null) // a fresh sync invalidates any prior voice report
    setReportError('')
    try {
      const data = await api.gmailSync(token, { unreadOnly, days })
      setItems(data.items)
      await loadStatus()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNeedsReconnect(true)
      } else if (err instanceof ApiError && err.status === 404) {
        setStatus({ connected: false })
      } else {
        setError(err instanceof ApiError ? err.detail : 'Sync failed')
      }
    } finally {
      setSyncing(false)
    }
  }

  async function handleVoiceReport() {
    if (!token || !items || items.length === 0) return
    setReportError('')
    setGenerating(true)
    try {
      setReport(await api.voiceReport(token, items))
    } catch (err) {
      setReportError(err instanceof ApiError ? err.detail : 'Could not generate the voice report')
    } finally {
      setGenerating(false)
    }
  }

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Inbox</h1>
          <p className="text-sm text-muted mt-1">Recent emails, triaged automatically.</p>
        </div>

        {notice && (
          <p className="text-sm text-ink-soft bg-brand-wash border border-line rounded-lg px-3 py-2">
            {notice}
          </p>
        )}
        {error && (
          <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
        )}

        {/* Connection card / header */}
        <Card className="p-6">
          {loadingStatus ? (
            <p className="text-sm text-muted">Checking Gmail connection…</p>
          ) : status?.connected ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <SectionHead kicker="Connected" title={status.google_email ?? 'Gmail'} />
                <p className="text-xs text-muted mt-1">Last sync: {relSync(status.last_synced_at)}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm text-ink-soft">
                  <input
                    type="checkbox"
                    checked={unreadOnly}
                    onChange={(e) => setUnreadOnly(e.target.checked)}
                    disabled={syncing}
                  />
                  Unread only
                </label>
                <select
                  className="text-sm border border-line rounded-lg bg-paper text-ink px-2 py-1.5"
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                  disabled={syncing}
                  aria-label="Look-back window"
                >
                  <option value={1}>Last 1 day</option>
                  <option value={3}>Last 3 days</option>
                  <option value={7}>Last 7 days</option>
                  <option value={30}>Last 30 days</option>
                </select>
                <Button onClick={handleSync} disabled={syncing}>
                  {syncing ? 'Fetching…' : 'Fetch emails'}
                </Button>
                {items && items.length > 0 && (
                  <Button variant="ghost" onClick={handleVoiceReport} disabled={generating || syncing}>
                    {generating ? 'Generating…' : 'Voice report'}
                  </Button>
                )}
                {canConnect && (
                  <Button variant="ghost" onClick={handleDisconnect}>
                    Disconnect
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <SectionHead
                kicker="Gmail"
                title="Connect your inbox"
                sub="Triage today's new emails without copy-pasting."
              />
              {canConnect ? (
                <>
                  <Button onClick={handleConnect}>Connect Gmail</Button>
                  <p className="text-xs text-muted">
                    Read-only. We never send or delete anything. You can disconnect anytime.
                  </p>
                </>
              ) : (
                <p className="text-sm text-muted">
                  Ask an owner or admin to connect a Gmail account for this workspace.
                </p>
              )}
            </div>
          )}
        </Card>

        {/* Reconnect banner */}
        {needsReconnect && (
          <Card className="p-4 border-crit">
            <div className="flex items-center justify-between gap-4">
              <p className="text-sm text-ink-soft">
                The Gmail connection expired. Reconnect to keep triaging your inbox.
              </p>
              {canConnect && (
                <Button variant="ghost" onClick={handleConnect}>
                  Reconnect
                </Button>
              )}
            </div>
          </Card>
        )}

        {/* Voice report (Plan 41) — briefing over the items already on screen */}
        {reportError && (
          <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{reportError}</p>
        )}
        {generating && (
          <Card className="p-6">
            <p className="text-sm text-muted">Writing your briefing…</p>
          </Card>
        )}
        {!generating && report && <VoiceScriptView report={report} />}

        {/* Loading skeleton */}
        {syncing && (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Card key={i} className="p-4">
                <div className="h-4 w-1/3 bg-ground rounded animate-pulse" />
                <div className="h-3 w-2/3 bg-ground rounded animate-pulse mt-2" />
              </Card>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!syncing && items !== null && items.length === 0 && (
          <Card className="p-8 text-center">
            <p className="text-lg text-ink">No new emails today 🎉</p>
            <p className="text-sm text-muted mt-1">Your inbox is all caught up.</p>
          </Card>
        )}

        {/* Inbox list */}
        {!syncing && items && items.length > 0 && (
          <div className="space-y-2">
            {items.map((item) => {
              const isOpen = expanded.has(item.message_id)
              return (
                <Card key={item.message_id} className="p-4">
                  <button
                    onClick={() => toggle(item.message_id)}
                    className="w-full flex items-center gap-3 text-left"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink truncate">{item.sender}</p>
                      <p className="text-sm text-muted truncate">{item.subject}</p>
                    </div>
                    <span className="text-xs text-faint shrink-0">{timeOf(item.received_at)}</span>
                  </button>
                  <div className="flex items-center gap-2 mt-3 pl-0">
                    <Tag tone="amber">{item.category}</Tag>
                    <span className="text-xs text-muted">
                      confidence {(item.confidence * 100).toFixed(0)}%
                    </span>
                    <span className="flex-1" />
                    <button
                      onClick={() => toggle(item.message_id)}
                      className="text-xs text-brand hover:underline"
                    >
                      {isOpen ? 'Hide' : 'View draft'}
                    </button>
                  </div>

                  {isOpen && (
                    <div className="mt-3 border-t border-line pt-3">
                      <p className="font-mono text-[11px] uppercase tracking-wide text-faint mb-2">
                        Draft reply
                      </p>
                      <div className="bg-ground rounded-lg p-4 text-sm text-ink-soft leading-relaxed border border-line whitespace-pre-wrap">
                        {item.draft_reply}
                      </div>
                      <button
                        onClick={() => navigator.clipboard.writeText(item.draft_reply)}
                        className="mt-2 text-xs text-brand hover:underline"
                      >
                        Copy reply
                      </button>

                      {can(user?.role, 'traces:read') && item.trace_id && token && user?.tenant_id && (
                        <div className="mt-3">
                          <DiagnosePanel token={token} tid={user.tenant_id} traceId={item.trace_id} />
                          <TraceChat token={token} tid={user.tenant_id} traceId={item.trace_id} />
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </AppShell>
  )
}
