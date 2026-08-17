import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { Category, TuningProposal } from '../api'
import { TraceDiagnosisView } from './TraceDiagnosisView'
import { Button, Card, Tag } from './ui/kit'

function ScoreLine({ label, score }: { label: string; score: TuningProposal['score_before'] }) {
  if (!score) return null
  return (
    <p className="text-xs text-muted font-mono">
      {label}: predicted <span className="text-ink-soft">{score.target_predicted}</span> ·{' '}
      {score.regressions} regression{score.regressions === 1 ? '' : 's'} / {score.checked} checked
    </p>
  )
}

// Pure render of a TuningProposal (Plan 44/F3). Reuses TraceDiagnosisView for the diagnosis.
// The UI NEVER publishes — the CTA points the human to Studio (Plan 26).
export function TuningProposalView({ proposal }: { proposal: TuningProposal }) {
  return (
    <div className="space-y-4">
      {proposal.diagnosis && (
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wide text-faint mb-2">Diagnosis</p>
          <TraceDiagnosisView diagnosis={proposal.diagnosis} />
        </div>
      )}

      <div>
        <div className="flex items-center gap-2 mb-2">
          <p className="font-mono text-[11px] uppercase tracking-wide text-faint">
            Draft changes ({proposal.cycles} cycle{proposal.cycles === 1 ? '' : 's'})
          </p>
          <Tag tone={proposal.gate_passed ? 'brand' : 'amber'}>
            {proposal.gate_passed ? 'gate passed' : 'not resolved'}
          </Tag>
        </div>
        {proposal.changes.length > 0 ? (
          <ul className="list-disc pl-5 space-y-1 text-sm text-ink-soft">
            {proposal.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No changes were made to the draft.</p>
        )}
      </div>

      <div className="space-y-1">
        <ScoreLine label="Before" score={proposal.score_before} />
        <ScoreLine label="After" score={proposal.score_after} />
      </div>

      <p className="text-sm text-ink whitespace-pre-wrap">{proposal.recommendation}</p>

      <div className="bg-brand-wash border border-line rounded-lg px-3 py-2 text-sm text-ink-soft">
        The changes live in your <strong>draft</strong>. Review and{' '}
        <Link to="/studio" className="text-brand hover:underline font-medium">
          publish in Studio
        </Link>{' '}
        to make them live.
      </div>
    </div>
  )
}

// Interactive block on the Dashboard result (Plan 44/F3). Owner-only (`prompt:publish`) — the
// caller gates rendering. `/tune` needs the full email (subject/sender/body), which only the
// Dashboard has (the Inbox item is body-less/ephemeral). The UI never publishes.
export function TuningPanel({
  token,
  tid,
  traceId,
  email,
}: {
  token: string
  tid: string
  traceId: string
  email: { subject: string; sender: string; body: string }
}) {
  const [open, setOpen] = useState(false)
  const [categories, setCategories] = useState<Category[] | null>(null)
  const [expected, setExpected] = useState('')
  const [proposal, setProposal] = useState<TuningProposal | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function openPanel() {
    setOpen(true)
    if (categories) return
    try {
      setCategories(await api.listCategories(token, tid))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not load categories')
    }
  }

  async function submit() {
    if (!expected || loading) return
    setError('')
    setLoading(true)
    try {
      setProposal(await api.tune(token, tid, { trace_id: traceId, email, expected_category: expected }))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Tuning failed')
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <button onClick={openPanel} className="text-xs text-muted hover:text-ink transition">
        ▸ Mis-classified? Suggest improvement
      </button>
    )
  }

  return (
    <div className="border-t border-line pt-4 mt-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[11px] uppercase tracking-wide text-brand font-semibold">
          Tuning copilot
        </p>
        <button onClick={() => setOpen(false)} className="text-xs text-muted hover:text-ink">
          Hide
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex-1 min-w-[12rem]">
          <span className="block text-xs text-muted mb-1">Expected category</span>
          <select
            value={expected}
            onChange={(e) => setExpected(e.target.value)}
            disabled={loading || !categories}
            className="w-full bg-paper border border-line rounded-lg px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-brand disabled:opacity-50"
          >
            <option value="">{categories ? 'Select…' : 'Loading…'}</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <Button onClick={submit} disabled={loading || !expected}>
          {loading ? 'Working…' : 'Suggest improvement'}
        </Button>
      </div>

      {loading && (
        <p className="text-xs text-faint">
          Diagnosing, editing the draft and re-checking — this can take a few seconds.
        </p>
      )}
      {error && (
        <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
      )}
      {proposal && (
        <Card className="p-4">
          <TuningProposalView proposal={proposal} />
        </Card>
      )}
    </div>
  )
}
