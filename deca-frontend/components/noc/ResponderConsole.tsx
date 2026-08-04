'use client'

import { FormEvent, useState } from 'react'

const SUGGESTIONS = [
  'Is NRSC healthy?',
  'Any congestion at SAC?',
  'What is confidence for policy_drift?',
  'Why is tunnel degraded at station1?',
]

export default function ResponderConsole({
  askBusy,
  askLog,
  onAsk,
}: {
  askBusy: boolean
  askLog: Array<{ q: string; a: string; path: string }>
  onAsk: (q: string) => Promise<unknown>
}) {
  const [q, setQ] = useState('')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const text = q.trim()
    if (!text || askBusy) return
    setQ('')
    await onAsk(text)
  }

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Ask</h2>
          <p className="deca-section-sub">
            Plain-language questions. Answers use analyzer ticks / declarations only (RAG off).
          </p>
        </div>
      </div>

      <div className="deca-suggest">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            className="deca-chip"
            disabled={askBusy}
            onClick={() => void onAsk(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="deca-ask-form">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask about a site or fault class…"
          className="deca-input flex-1"
        />
        <button type="submit" disabled={askBusy} className="deca-btn deca-btn-primary">
          {askBusy ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      <div className="deca-ask-log">
        {askLog.length === 0 ? (
          <p className="deca-empty-sm">Answers appear here with a generation_path tag for honesty.</p>
        ) : (
          askLog.map((row, i) => (
            <article key={`${row.q}-${i}`} className="deca-ask-item">
              <p className="q">You · {row.q}</p>
              <p className="a">{row.a}</p>
              <p className="path">[{row.path}]</p>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
