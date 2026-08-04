'use client'

import { Square, Zap } from 'lucide-react'

export interface FaultInfo {
  id: string
  label: string
  blurb: string
  duration_hint_s?: number
}

export interface FaultDemoStatus {
  running?: boolean
  fault_id?: string | null
  label?: string
  message?: string
  seeded_alert?: number | null
  log_tail?: string[]
  catalog?: FaultInfo[]
}

const FALLBACK: FaultInfo[] = [
  { id: 'rain_fade', label: 'Rain fade', blurb: 'GRE latency ramp' },
  { id: 'cpu_stress', label: 'CPU / crypto', blurb: 'PE CPU burn' },
  { id: 'bgp_flap', label: 'BGP flap', blurb: 'Route instability' },
  { id: 'ce_sla_conflict', label: 'CE SLA conflict', blurb: 'Bronze vs Gold' },
  { id: 'loss_progression', label: 'Loss ramp', blurb: 'GRE loss climb' },
]

export default function FaultButtons({
  status,
  busy,
  fabric = 'pi',
  onStart,
  onClear,
}: {
  status: FaultDemoStatus | null
  busy: boolean
  fabric?: string
  onStart: (faultId: string) => void
  onClear: () => void
}) {
  const catalog =
    status?.catalog && status.catalog.length > 0 ? status.catalog : FALLBACK
  const running = Boolean(status?.running)
  const activeId = status?.fault_id || null

  return (
    <section className="deca-panel deca-sim">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Simple faults</h2>
          <p className="deca-section-sub">
            Click one fault → inject on <span className="font-mono">{fabric}</span>{' '}
            → Decide predicts. Approve steers backup.
          </p>
        </div>
        <button
          type="button"
          className="deca-btn-ghost"
          disabled={busy}
          onClick={onClear}
          title="Stop inject and clear netem/stress leftovers"
        >
          <Square className="w-3.5 h-3.5" />
          Clear
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mt-3">
        {catalog.map((f) => {
          const isActive = running && activeId === f.id
          return (
            <button
              key={f.id}
              type="button"
              className={isActive ? 'deca-btn-primary' : 'deca-btn-ghost'}
              disabled={busy || (running && !isActive)}
              onClick={() => onStart(f.id)}
              title={f.blurb}
            >
              <Zap className="w-3.5 h-3.5" />
              {f.label}
            </button>
          )
        })}
      </div>

      <p className="deca-section-sub mt-3">
        {status?.message || 'Idle — pick a fault when stations are up.'}
        {status?.seeded_alert != null ? (
          <span className="font-mono"> · alert #{status.seeded_alert}</span>
        ) : null}
      </p>
      {Array.isArray(status?.log_tail) && status!.log_tail!.length > 0 ? (
        <pre className="mt-2 max-h-24 overflow-auto rounded border border-[var(--deca-border)] bg-[var(--deca-panel-2,#0f172a)]/50 p-2 text-[10px] font-mono text-[var(--deca-mute)]">
          {status!.log_tail!.slice(-8).join('\n')}
        </pre>
      ) : null}
    </section>
  )
}
