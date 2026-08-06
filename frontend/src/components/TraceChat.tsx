import { useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { TraceChatMessage } from '../api'

// Chat panel anchored to one triage's trace (Plan 32). Owner/admin only — the caller
// gates rendering with `can(role, 'traces:read')`; the backend re-checks every request
// and scopes every Logfire query to the workspace's tenant.
export function TraceChat({
  token,
  tid,
  traceId,
}: {
  token: string
  tid: string
  traceId: string
}) {
  const [messages, setMessages] = useState<TraceChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const threadRef = useRef<HTMLDivElement>(null)

  async function send(e: React.FormEvent) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) return
    setError('')
    setInput('')
    const history = messages
    const next = [...messages, { role: 'user' as const, content: question }]
    setMessages(next)
    setLoading(true)
    try {
      const { reply } = await api.traceChat(token, tid, traceId, question, history)
      setMessages([...next, { role: 'assistant', content: reply }])
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong')
      setMessages(history) // roll back the optimistic user turn on failure
      setInput(question)
    } finally {
      setLoading(false)
      requestAnimationFrame(() => {
        threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight })
      })
    }
  }

  return (
    <div className="border-t border-gray-200 pt-4 mt-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500">Debug this trace</p>
        <code className="text-[10px] text-gray-400" title="OTel trace id">
          {traceId.slice(0, 12)}…
        </code>
      </div>

      <div ref={threadRef} className="max-h-72 overflow-y-auto space-y-2 pr-1">
        {messages.length === 0 && !loading && (
          <p className="text-xs text-gray-400">
            Ask why this triage behaved as it did — latency, category, confidence, errors.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm rounded-lg px-3 py-2 whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-indigo-50 text-indigo-900 ml-6'
                : 'bg-gray-50 text-gray-700 mr-6'
            }`}
          >
            {m.content}
          </div>
        ))}
        {loading && <p className="text-xs text-gray-400 mr-6">Reading traces…</p>}
      </div>

      {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      <form onSubmit={send} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
          placeholder="e.g. Why was this slow?"
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg px-4 text-sm transition"
        >
          Ask
        </button>
      </form>
    </div>
  )
}
