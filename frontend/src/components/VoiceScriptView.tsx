import { useState } from 'react'
import type { VoiceReport } from '../api'
import { Card, SectionHead, Tag } from './ui/kit'

// Renders a voice-report script (Plan 41): headline + per-category counts + the spoken
// script (opening → sections → closing), with a "copy" button. `audio_url` is ignored in
// v1 (always null; the hook stays for future TTS).
function scriptToText(report: VoiceReport): string {
  const { opening, sections, closing } = report.script
  return [opening, ...sections.map((s) => `${s.heading}\n${s.body}`), closing]
    .filter(Boolean)
    .join('\n\n')
}

export function VoiceScriptView({ report }: { report: VoiceReport }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(scriptToText(report))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Card className="p-6 space-y-4">
      <SectionHead
        kicker="Voice report"
        title={report.headline}
        actions={<span className="text-xs text-muted">{report.total} emails</span>}
      />

      {report.by_category.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {report.by_category.map((c) => (
            <Tag key={c.category} tone="amber">
              {c.category} · {c.count}
            </Tag>
          ))}
        </div>
      )}

      <div className="bg-ground rounded-lg p-4 border border-line space-y-3 text-sm text-ink-soft leading-relaxed">
        <p className="whitespace-pre-wrap">{report.script.opening}</p>
        {report.script.sections.map((s, i) => (
          <div key={i}>
            <p className="font-medium text-ink">{s.heading}</p>
            <p className="whitespace-pre-wrap">{s.body}</p>
          </div>
        ))}
        <p className="whitespace-pre-wrap">{report.script.closing}</p>
      </div>

      <button onClick={copy} className="text-xs text-brand hover:underline">
        {copied ? 'Copied ✓' : 'Copy script'}
      </button>
    </Card>
  )
}
