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
  phase?: string
  log_tail?: string[]
  catalog?: FaultInfo[]
  model_detection?: {
    ok?: boolean
    severity?: string | null
    q2_confidence?: number | null
    eta_minutes?: number | null
    raise?: boolean
    explanation?: string | null
  } | null
}

/** Jury-friendly one-liners (override catalog blurbs when they are ops jargon). */
const PLAIN_BLURB: Record<string, string> = {
  rain_fade: 'Slows the primary satellite path (like weather fade)',
  cpu_stress: 'Overloads the router so encrypted traffic struggles',
  bgp_flap: 'Shakes the routing table — paths keep flipping',
  ce_sla_conflict: 'Lower-priority site crowds out a critical mission site',
  loss_progression: 'Packet loss climbs on the primary path',
}

const FALLBACK: FaultInfo[] = [
  { id: 'rain_fade', label: 'Rain fade', blurb: PLAIN_BLURB.rain_fade },
  { id: 'cpu_stress', label: 'CPU / crypto', blurb: PLAIN_BLURB.cpu_stress },
  { id: 'bgp_flap', label: 'BGP flap', blurb: PLAIN_BLURB.bgp_flap },
  { id: 'ce_sla_conflict', label: 'SLA conflict', blurb: PLAIN_BLURB.ce_sla_conflict },
  { id: 'loss_progression', label: 'Loss ramp', blurb: PLAIN_BLURB.loss_progression },
]

const PHASE_PLAIN: Record<string, string> = {
  idle: 'Ready',
  injecting: 'Fault running — waiting for model…',
  seeded: 'Model card ready — Approve on the right, or wait',
  collapsing: 'No Approve — ending inject, settling…',
  steered: 'Approved — inject stopped, settling…',
  recovering: 'Settling naturally — waiting for path to look healthy…',
  healthy: 'Healthy again',
}

export default function FaultButtons({
  status,
  busy,
  fabric = 'pi',
  onStart,
  onClear,
  embedded = false,
}: {
  status: FaultDemoStatus | null
  busy: boolean
  fabric?: string
  onStart: (faultId: string) => void
  onClear: () => void
  embedded?: boolean
}) {
  const catalog =
    status?.catalog && status.catalog.length > 0 ? status.catalog : FALLBACK
  const running = Boolean(status?.running)
  const activeId = status?.fault_id || null
  const phase = status?.phase || 'idle'
  const phaseLine = PHASE_PLAIN[phase] || status?.message || 'Ready'

  const Wrap = embedded ? 'div' : 'section'
  return (
    <Wrap className={embedded ? 'deca-lab-embed' : 'deca-panel deca-sim'}>
      <div className="deca-panel-head">
        <div>
          <h2 className={embedded ? 'deca-lab-slot-title' : 'deca-section-title'}>
            Inject a problem
          </h2>
          <p className="deca-section-sub">
            One click starts a live fault on the {fabric === 'gns3' ? 'GNS3' : 'Pi'} network.
            Watch the right column for the prediction.
          </p>
        </div>
        <button
          type="button"
          className="deca-btn-ghost"
          disabled={busy}
          onClick={onClear}
          title="Stop the fault and return the network to healthy"
        >
          <Square className="w-3.5 h-3.5" />
          Stop fault
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mt-3">
        {catalog.map((f) => {
          const isActive = running && activeId === f.id
          const tip = PLAIN_BLURB[f.id] || f.blurb
          return (
            <button
              key={f.id}
              type="button"
              className={isActive ? 'deca-btn-primary' : 'deca-btn-ghost'}
              disabled={busy || (running && !isActive)}
              onClick={() => onStart(f.id)}
              title={tip}
            >
              <Zap className="w-3.5 h-3.5" />
              {f.label}
            </button>
          )
        })}
      </div>

      <p className="deca-section-sub mt-3">
        <strong>{phaseLine}</strong>
        {status?.message && phase !== 'idle' ? (
          <span className="text-[var(--deca-mute)]"> — {status.message}</span>
        ) : null}
      </p>
    </Wrap>
  )
}
