'use client'

import { Play, Square } from 'lucide-react'

export interface SimulationStatus {
  running?: boolean
  finished?: boolean
  ok?: boolean
  phase?: number | null
  phase_name?: string | null
  message?: string
  ui_expectation?: string
  waiting_for_approve?: boolean
  elapsed_s?: number
  dry?: boolean
  log_tail?: string[]
  error?: string
}

const PHASES = [
  { id: 0, label: 'Init' },
  { id: 1, label: 'Clear weather' },
  { id: 2, label: 'Payload tolerance' },
  { id: 3, label: 'Hard steer' },
  { id: 4, label: 'AI + Approve' },
  { id: 5, label: 'Recovery' },
  { id: 6, label: 'Teardown' },
]

export default function SimulationControl({
  status,
  busy,
  onStart,
  onStop,
}: {
  status: SimulationStatus | null
  busy: boolean
  onStart: (dry: boolean) => void
  onStop: () => void
}) {
  const running = Boolean(status?.running)
  const phase = status?.phase ?? null
  const waiting = Boolean(status?.waiting_for_approve)

  return (
    <section className="deca-panel deca-sim">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Full lab timeline</h2>
          <p className="deca-section-sub">
            Phases 0–6 on the <strong>active fabric</strong> (Pi SSH or GNS3 iperf3+NetEM). Prefer{' '}
            <strong>Simple faults</strong> above for short jury demos.
          </p>
        </div>
        <div className="deca-sim-actions">
          <button
            type="button"
            className="deca-btn-primary"
            disabled={busy || running}
            onClick={() => onStart(false)}
            title="Run on active fabric (Pi stations or GNS3 injects)"
          >
            <Play className="w-3.5 h-3.5" />
            Start
          </button>
          <button
            type="button"
            className="deca-btn-ghost"
            disabled={busy || running}
            onClick={() => onStart(true)}
            title="Advance timeline without live injects"
          >
            Dry run
          </button>
          <button
            type="button"
            className="deca-btn-ghost"
            disabled={busy || !running}
            onClick={onStop}
          >
            <Square className="w-3.5 h-3.5" />
            Stop
          </button>
        </div>
      </div>

      <ol className="deca-sim-phases">
        {PHASES.map((p) => {
          const active = phase === p.id && running
          const done = phase != null && phase > p.id
          return (
            <li
              key={p.id}
              className={`deca-sim-phase${active ? ' is-active' : ''}${done ? ' is-done' : ''}`}
            >
              <span className="deca-sim-phase-id">P{p.id}</span>
              <span>{p.label}</span>
            </li>
          )
        })}
      </ol>

      <div className={`deca-sim-status${waiting ? ' is-wait' : ''}`}>
        <p className="deca-sim-msg">
          {status?.phase_name ? (
            <>
              <span className="font-mono text-xs opacity-70">
                T≈{status.elapsed_s ?? 0}s · P{status.phase}
              </span>{' '}
              {status.phase_name}
            </>
          ) : (
            'Idle — press Start for a clean timeline (clears prior Decide/history on this fabric).'
          )}
        </p>
        {status?.message ? <p className="deca-sim-detail">{status.message}</p> : null}
        {status?.ui_expectation ? (
          <p className="deca-sim-ui">UI: {status.ui_expectation}</p>
        ) : null}
        {waiting ? (
          <p className="deca-sim-hitl">
            Waiting for Approve on the Decide rail — steers via POST /action before SLA breach.
          </p>
        ) : null}
        {status?.finished && !running ? (
          <p className="deca-sim-detail">
            Finished{status.ok === false ? ' with errors' : ''}.
          </p>
        ) : null}
      </div>
    </section>
  )
}
