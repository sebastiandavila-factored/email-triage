import { useState } from 'react'
import { api, ApiError } from '../api'
import type { FixKind, TraceDiagnosis } from '../api'
import { Card, Tag } from './ui/kit'

// Human labels for the backend FixKind enum.
const FIX_LABELS: Record<FixKind, string> = {
  add_counter_example: 'Add counter-example',
  tweak_category: 'Tweak category',
  adjust_examples: 'Adjust examples',
  none: 'No change',
}

// Pure verdict card (Plan 43). Reused by the tuning panel (Plan 44/F3), which shows the same
// diagnosis inline. No fetching here — the caller supplies the diagnosis.
export function TraceDiagnosisView({ diagnosis }: { diagnosis: TraceDiagnosis }) {
  const [showEvidence, setShowEvidence] = useState(false)
  const pct = Math.round(diagnosis.confidence * 100)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone="brand">{FIX_LABELS[diagnosis.suggested_fix_kind]}</Tag>
        {diagnosis.target_slug && <Tag tone="amber">{diagnosis.target_slug}</Tag>}
        <span className="text-xs text-muted">confidence {pct}%</span>
      </div>

      <div>
        <p className="font-mono text-[11px] uppercase tracking-wide text-faint mb-1">Root cause</p>
        <p className="text-sm text-ink whitespace-pre-wrap">{diagnosis.root_cause}</p>
      </div>

      <div className="h-1.5 w-full rounded-full bg-ground overflow-hidden" aria-hidden>
        <div className="h-full bg-brand rounded-full" style={{ width: `${pct}%` }} />
      </div>

      <div>
        <p className="font-mono text-[11px] uppercase tracking-wide text-faint mb-1">Rationale</p>
        <p className="text-sm text-ink-soft whitespace-pre-wrap">{diagnosis.rationale}</p>
      </div>

      {diagnosis.evidence.length > 0 && (
        <div>
          <button
            onClick={() => setShowEvidence((v) => !v)}
            className="text-xs text-brand hover:underline"
          >
            {showEvidence ? '▾ Hide evidence' : `▸ Evidence (${diagnosis.evidence.length})`}
          </button>
          {showEvidence && (
            <ul className="mt-2 space-y-1">
              {diagnosis.evidence.map((e, i) => (
                <li key={i} className="text-xs text-muted font-mono">
                  {e.span_name}
                  {e.duration_ms != null && ` · ${e.duration_ms.toFixed(0)}ms`}
                  {e.note && <span className="text-ink-soft"> · {e.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

// Button + fetch wrapper (Plan 43/F2). Mounted next to TraceChat on the Dashboard and Inbox.
// Same gating as "Ver traces" (`traces:read`) — enforced by the caller and re-checked server-side.
export function DiagnosePanel({
  token,
  tid,
  traceId,
}: {
  token: string
  tid: string
  traceId: string
}) {
  const [diagnosis, setDiagnosis] = useState<TraceDiagnosis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    if (loading) return
    setError('')
    setLoading(true)
    try {
      setDiagnosis(await api.diagnoseTrace(token, tid, traceId))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Diagnosis failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="border-t border-line pt-4 mt-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[11px] uppercase tracking-wide text-brand font-semibold">
          Diagnose this trace
        </p>
        <button
          onClick={run}
          disabled={loading}
          className="text-xs text-brand hover:underline disabled:opacity-50"
        >
          {loading ? 'Diagnosing…' : diagnosis ? 'Re-run' : 'Diagnose'}
        </button>
      </div>

      {!diagnosis && !loading && !error && (
        <p className="text-xs text-faint">
          Run an automated root-cause analysis over this triage's trace.
        </p>
      )}
      {error && (
        <p className="text-sm text-crit border border-line rounded-lg px-3 py-2">{error}</p>
      )}
      {diagnosis && (
        <Card className="p-4">
          <TraceDiagnosisView diagnosis={diagnosis} />
        </Card>
      )}
    </div>
  )
}
