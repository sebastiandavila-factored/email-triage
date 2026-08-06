import { useEffect, useRef, useState } from 'react'
import { useAuth, ApiError } from '../AuthContext'
import { api } from '../api'
import type { TriageResponse } from '../api'
import { AppShell } from '../components/ui/AppShell'

// Per-category accent via the shared --cat-* tokens (theme-aware). Falls back to muted.
const CATEGORY_VAR: Record<string, string> = {
  status: '--cat-status',
  refunds: '--cat-refunds',
  availability: '--cat-availability',
  shipments: '--cat-shipments',
  prices: '--cat-prices',
}
function categoryStyle(category: string): React.CSSProperties {
  return { color: `var(${CATEGORY_VAR[category] ?? '--cat-unknown'})` }
}

interface Example {
  key: string
  label: string
  hint: string
  subject: string
  sender: string
  body: string
}

const EXAMPLES: Example[] = [
  {
    key: 'simple',
    label: 'Simple',
    hint: 'one question · short reply · fast',
    subject: 'Where is my order #4821?',
    sender: 'customer@example.com',
    body: "Hi, I ordered three days ago and still have no tracking number. Can you tell me when it will ship and arrive? I'm getting worried. Thanks.",
  },
  {
    key: 'complex',
    label: 'Complex (long reply)',
    hint: '4 distinct issues · ambiguous category · long reply',
    subject: 'Multiple problems with order #7732 — need help urgently',
    sender: 'frustrated.customer@example.com',
    body: `Hello, I'm really disappointed. I received order #7732 yesterday but there are several problems and I need clear answers on each:

1) You sent the blue model but I ordered the black one. I want to return it — who pays the return shipping, and how long does a refund take to appear on my card?
2) If I return it, is the black model actually in stock right now? I don't want to wait weeks again.
3) I used the code WELCOME15 at checkout but the 15% discount was never applied to my total. Can you fix the price difference?
4) My original delivery was 6 days late with no notification. What compensation do you offer?

Please address every single point clearly and tell me the exact next steps. I've been a customer for years and this experience has been frustrating.`,
  },
]

type Status = 'idle' | 'running' | 'done' | 'error'
interface SyncState {
  status: Status
  result?: TriageResponse
  ms?: number
  error?: string
}
interface StreamState {
  status: Status
  category?: string
  confidence?: number
  ttft?: number
  draft: string
  ms?: number
  error?: string
}

function CategoryBadge({ category }: { category?: string }) {
  if (!category) return null
  return (
    <span
      style={categoryStyle(category)}
      className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide bg-ground border border-line"
    >
      {category}
    </span>
  )
}

export function Compare() {
  const { token, apiKey } = useAuth()
  const [subject, setSubject] = useState(EXAMPLES[0].subject)
  const [sender, setSender] = useState(EXAMPLES[0].sender)
  const [body, setBody] = useState(EXAMPLES[0].body)
  const [sync, setSync] = useState<SyncState>({ status: 'idle' })
  const [stream, setStream] = useState<StreamState>({ status: 'idle', draft: '' })
  const [nowMs, setNowMs] = useState(0)
  const [error, setError] = useState('')
  const timer = useRef<number | null>(null)
  const t0 = useRef(0)

  // Clear the ticker if we unmount mid-run.
  useEffect(() => () => stopTimer(), [])

  function stopTimer() {
    if (timer.current !== null) {
      clearInterval(timer.current)
      timer.current = null
    }
  }

  function loadExample(ex: Example) {
    setSubject(ex.subject)
    setSender(ex.sender)
    setBody(ex.body)
    setSync({ status: 'idle' })
    setStream({ status: 'idle', draft: '' })
    setError('')
  }

  function run(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    if (!apiKey) {
      setError('API key not set. Go to Settings to enter or rotate your API key.')
      return
    }
    setError('')
    setSync({ status: 'running' })
    setStream({ status: 'running', draft: '' })
    t0.current = performance.now()
    setNowMs(0)
    stopTimer()
    timer.current = window.setInterval(
      () => setNowMs(Math.round(performance.now() - t0.current)),
      40,
    )

    let syncDone = false
    let streamDone = false
    const maybeStop = () => {
      if (syncDone && streamDone) stopTimer()
    }
    const since = () => Math.round(performance.now() - t0.current)

    // Left — synchronous /triage: nothing until the whole thing is ready.
    api
      .triage(token, apiKey, subject, sender, body)
      .then((result) => setSync({ status: 'done', result, ms: since() }))
      .catch((err) =>
        setSync({ status: 'error', error: err instanceof ApiError ? err.detail : 'Error' }),
      )
      .finally(() => {
        syncDone = true
        maybeStop()
      })

    // Right — streaming /triage/stream: category early, draft token by token.
    void api.triageStream(
      token,
      apiKey,
      { subject, sender, body },
      {
        onMeta: (category, confidence) =>
          setStream((s) => ({ ...s, category, confidence, ttft: s.ttft ?? since() })),
        onDelta: (text) =>
          setStream((s) => ({ ...s, draft: s.draft + text, ttft: s.ttft ?? since() })),
        onDone: () => {
          setStream((s) => ({ ...s, status: 'done', ms: since() }))
          streamDone = true
          maybeStop()
        },
        onError: (err) => {
          setStream((s) => ({
            ...s,
            status: 'error',
            error: err instanceof ApiError ? err.detail : 'Error',
          }))
          streamDone = true
          maybeStop()
        },
      },
    )
  }

  const running = sync.status === 'running' || stream.status === 'running'

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Sync vs. Streaming</h1>
          <p className="text-sm text-muted mt-1">
            The same request on the left (<code>/triage</code> — you wait for the whole result) and on
            the right (<code>/triage/stream</code> — the category shows instantly and the draft types
            itself out). Watch the TTFT.
          </p>
        </div>

        {/* Shared input */}
        <form onSubmit={run} className="bg-paper rounded-2xl border border-line p-6 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-faint">Load example:</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex.key}
                type="button"
                onClick={() => loadExample(ex)}
                title={ex.hint}
                className="text-xs border border-line rounded-full px-3 py-1 text-ink-soft hover:bg-ground"
              >
                {ex.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <input
              type="text"
              required
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject"
              className="border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
            />
            <input
              type="text"
              required
              value={sender}
              onChange={(e) => setSender(e.target.value)}
              placeholder="From"
              className="border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
            />
          </div>
          <textarea
            required
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Email body"
            className="w-full border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand resize-none"
          />
          {error && <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>}
          <button
            type="submit"
            disabled={running}
            className="w-full bg-brand hover:bg-brand-bright disabled:opacity-50 text-paper font-medium rounded-lg py-2.5 text-sm transition"
          >
            {running ? 'Running both…' : 'Run comparison ▶'}
          </button>
        </form>

        {/* Side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* SYNC */}
          <Panel title="Sync · /triage" subtitle="Blocking: nothing until it's done">
            <Clock
              label="Total"
              ms={sync.status === 'done' ? sync.ms : sync.status === 'running' ? nowMs : undefined}
              running={sync.status === 'running'}
            />
            {sync.status === 'running' && (
              <p className="text-sm text-faint animate-pulse mt-3">Waiting for the full response…</p>
            )}
            {sync.status === 'error' && <p className="text-sm text-crit mt-3">{sync.error}</p>}
            {sync.status === 'done' && sync.result && (
              <div className="mt-3 space-y-3">
                <CategoryBadge category={sync.result.category} />
                <div className="bg-ground rounded-lg p-4 text-sm text-ink-soft leading-relaxed whitespace-pre-wrap">
                  {sync.result.draft_reply}
                </div>
              </div>
            )}
          </Panel>

          {/* STREAM */}
          <Panel title="Streaming · /triage/stream" subtitle="Incremental: category + tokens live">
            <div className="flex gap-4">
              <Clock
                label="TTFT"
                ms={stream.ttft}
                running={stream.status === 'running' && stream.ttft === undefined}
                highlight
              />
              <Clock
                label="Total"
                ms={
                  stream.status === 'done'
                    ? stream.ms
                    : stream.status === 'running'
                      ? nowMs
                      : undefined
                }
                running={stream.status === 'running'}
              />
            </div>
            {stream.status === 'error' && <p className="text-sm text-crit mt-3">{stream.error}</p>}
            {stream.status !== 'idle' && stream.status !== 'error' && (
              <div className="mt-3 space-y-3">
                {stream.category ? (
                  <CategoryBadge category={stream.category} />
                ) : (
                  <span className="text-xs text-faint">waiting for category…</span>
                )}
                <div className="bg-ground rounded-lg p-4 text-sm text-ink-soft leading-relaxed whitespace-pre-wrap min-h-[3rem]">
                  {stream.draft}
                  {stream.status === 'running' && (
                    <span className="inline-block w-1.5 h-4 bg-brand ml-0.5 align-middle animate-pulse" />
                  )}
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </AppShell>
  )
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-paper rounded-2xl border border-line p-6">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <p className="text-xs text-faint mb-4">{subtitle}</p>
      {children}
    </div>
  )
}

function Clock({
  label,
  ms,
  running,
  highlight,
}: {
  label: string
  ms?: number
  running: boolean
  highlight?: boolean
}) {
  return (
    <div>
      <div className="text-xs text-faint">{label}</div>
      <div
        className={`font-mono text-lg ${highlight ? 'text-brand' : 'text-ink'} ${running ? 'animate-pulse' : ''}`}
      >
        {ms === undefined ? '—' : `${ms} ms`}
      </div>
    </div>
  )
}
