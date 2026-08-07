'use client'

import { Play, Square } from 'lucide-react'
import type { TrafficStatus } from '@/lib/api'

const PROFILES: Array<{ id: string; label: string; blurb: string }> = [
  { id: 'ttc', label: 'TT&C', blurb: 'UDP 1M · ToS 0x88' },
  { id: 'payload', label: 'Payload', blurb: 'UDP 20M · ToS 0x80' },
  { id: 'admin', label: 'Admin', blurb: 'TCP BE / scavenger' },
  { id: 'mixed', label: 'Mixed', blurb: 'All three classes' },
]

export default function TrafficButtons({
  status,
  busy,
  fabric = 'pi',
  onStart,
  onStop,
  embedded = false,
}: {
  status: TrafficStatus | null
  busy: boolean
  fabric?: string
  onStart: (profile: string) => void
  onStop: () => void
  embedded?: boolean
}) {
  const running = Boolean(status?.running)
  const active = status?.profile || null

  const Wrap = embedded ? 'div' : 'section'
  return (
    <Wrap className={embedded ? 'deca-lab-embed' : 'deca-panel deca-sim'}>
      <div className="deca-panel-head">
        <div>
          <h2 className={embedded ? 'deca-lab-slot-title' : 'deca-section-title'}>
            Traffic
          </h2>
          {!embedded ? (
            <p className="deca-section-sub">
              Start ToS streams on <span className="font-mono">{fabric}</span>
              {fabric === 'gns3'
                ? ' (IPERF-A→B through PE HTB — no GNS3 GUI needed)'
                : ' (iperf3 on CE netns)'}
              . Then inject a Simple fault and watch the map.
            </p>
          ) : null}
        </div>
        {running ? (
          <button
            type="button"
            className="deca-btn-ghost"
            disabled={busy}
            onClick={() => onStop()}
            title="Stop traffic generators"
          >
            <Square className="w-3.5 h-3.5" />
            Stop
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2 mt-3">
        {PROFILES.map((p) => {
          const isActive = running && active === p.id
          return (
            <button
              key={p.id}
              type="button"
              className={isActive ? 'deca-btn-primary' : 'deca-btn-ghost'}
              disabled={busy || (running && !isActive)}
              onClick={() => onStart(p.id)}
              title={p.blurb}
            >
              <Play className="w-3.5 h-3.5" />
              {p.label}
            </button>
          )
        })}
      </div>

      <p className="deca-section-sub mt-3 font-mono text-[11px]">
        {status?.message || 'idle'}
        {running && active ? ` · profile=${active}` : ''}
      </p>
    </Wrap>
  )
}
