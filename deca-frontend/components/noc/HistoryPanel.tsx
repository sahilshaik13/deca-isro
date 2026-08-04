'use client'

export default function HistoryPanel({
  history,
}: {
  history: {
    alerts?: unknown[]
    queries?: Array<{ id: number; ts: string; question: string; answer: string; generation_path: string }>
    actions?: Array<{
      id: number
      ts: string
      alert_id: number | null
      action: string
      operator_note: string
      result?: unknown
    }>
  } | null
}) {
  const actions = history?.actions || []
  const queries = history?.queries || []

  const resultOk = (result: unknown): boolean | null => {
    if (result && typeof result === 'object' && 'ok' in result) {
      return Boolean((result as { ok?: boolean }).ok)
    }
    return null
  }

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Audit trail</h2>
          <p className="deca-section-sub">SQLite history for this run — asks and gated steers.</p>
        </div>
      </div>

      <div className="deca-history-grid">
        <div>
          <h3 className="deca-field-label mb-2">Actions</h3>
          {actions.length === 0 ? (
            <p className="deca-empty-sm">No approve / reject yet.</p>
          ) : (
            <ul className="deca-history-list">
              {actions.slice(0, 12).map((a) => {
                const ok = resultOk(a.result)
                return (
                  <li key={a.id}>
                    <span className={`tag ${a.action}`}>{a.action}</span>
                    <span>
                      alert #{a.alert_id} · {a.ts}
                      {ok === true ? ' · controller ack' : ok === false ? ' · controller fail' : ''}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        <div>
          <h3 className="deca-field-label mb-2">Queries</h3>
          {queries.length === 0 ? (
            <p className="deca-empty-sm">No asks yet.</p>
          ) : (
            <ul className="deca-history-list">
              {queries.slice(0, 12).map((q) => (
                <li key={q.id}>
                  <span className="tag ask">ask</span>
                  <span>
                    {q.question}
                    <em className="block text-[var(--deca-mute)] font-normal not-italic">{q.ts}</em>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}
