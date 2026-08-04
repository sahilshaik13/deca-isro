'use client'

import { Cable, Network } from 'lucide-react'
import type { FabricId, FabricStatus } from '@/lib/api'

export type { FabricId }

const FALLBACK = [
  {
    id: 'pi' as const,
    label: 'Pi stations',
    blurb: 'Live Raspberry Pi SD-WAN fabric',
    ready: true,
    sla_label: 'TT&C≤25ms · Gold 99.9%',
  },
  {
    id: 'gns3' as const,
    label: 'GNS3 sim',
    blurb: 'Headless GNS3 · drive from NOC',
    ready: false,
    sla_label: 'TT&C≤25ms · Gold 99.9% (aligned)',
  },
]

export default function FabricSelect({
  status,
  busy,
  onSelect,
}: {
  status: FabricStatus | null
  busy: boolean
  onSelect: (fabric: FabricId) => void
}) {
  const fabrics =
    status?.fabrics && status.fabrics.length > 0 ? status.fabrics : FALLBACK
  const active = status?.active || 'pi'
  const mounted = status?.storage?.gns3_mounted
  const sla = status?.sla
  const ttc = sla?.classes?.ttc
  const gold = sla?.ce_tiers?.['ce-a']
  const exporterOk = status?.prometheus?.gns3_exporter_ok

  return (
    <section className="deca-panel deca-sim">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Simulation source</h2>
          <p className="deca-section-sub">
            Select fabric → Start traffic → Simple fault → watch map/telemetry →
            Decide. GNS3 GUI not required (server + Start-all once).
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mt-3">
        {fabrics.map((f) => {
          const isActive = active === f.id
          const Icon = f.id === 'gns3' ? Network : Cable
          return (
            <button
              key={f.id}
              type="button"
              className={isActive ? 'deca-btn-primary' : 'deca-btn-ghost'}
              disabled={busy}
              onClick={() => onSelect(f.id)}
              title={`${f.blurb}${f.sla_label ? ` · ${f.sla_label}` : ''}`}
            >
              <Icon className="w-3.5 h-3.5" />
              {f.label}
              {f.ready === false ? ' · setup' : ''}
            </button>
          )
        })}
      </div>

      <p className="deca-section-sub mt-3">
        Active: <span className="font-mono">{active}</span>
        {sla?.label ? (
          <>
            {' '}
            · {sla.label}
            {ttc?.latency_ms != null ? ` · TT&C ≤${ttc.latency_ms}ms` : null}
            {gold?.availability != null ? ` · Gold ${gold.availability}%` : null}
          </>
        ) : null}
        {active === 'gns3' && mounted === false
          ? " — mount /media/brain/Shaik's before starting GNS3"
          : null}
        {active === 'gns3' &&
        mounted !== false &&
        fabrics.find((x) => x.id === 'gns3')?.ready === false
          ? ' — touch DECA_READY after Start-all'
          : null}
        {active === 'gns3' && exporterOk === false
          ? ' — start exporter: python3 lab/gns3/exporters/gns3_path_exporter.py'
          : null}
        {active === 'pi'
          ? ' — leave Simple faults idle while protocol campaign owns injectors'
          : null}
      </p>
      {Array.isArray(sla?.chaos) && sla!.chaos!.length > 0 ? (
        <p className="deca-section-sub mt-1">
          Chaos tools: <span className="font-mono">{sla!.chaos!.join(' · ')}</span>
        </p>
      ) : null}
    </section>
  )
}
