'use client'

import type { FleetSite } from '@/lib/api'

const CLASS_LABEL: Record<string, string> = {
  ttc: 'TT&C',
  payload: 'Payload',
  be: 'Scavenger',
}

function siteTone(status: string) {
  if (status === 'alert') return 'warn'
  if (status === 'ok') return 'ok'
  return 'mute'
}

function liveRtt(site: FleetSite): number | null {
  const m = site.hosts_state?.[0]?.metrics as
    | { latency_gre_ms?: number; jitter_ms?: number }
    | undefined
  const lat = m?.latency_gre_ms ?? m?.jitter_ms
  return lat != null && Number.isFinite(lat) ? Number(lat) : null
}

export default function FleetStrip({ sites }: { sites: FleetSite[] }) {
  if (!sites.length) {
    return (
      <section className="deca-fleet-empty">
        Bind a run above to load NRSC / Mauritius / SAC / MCF / CORE.
      </section>
    )
  }

  return (
    <section className="deca-fleet" aria-label="Fleet status">
      {sites.map((site) => {
        const tick = site.hosts_state?.[0]
        const tone = siteTone(site.status)
        const confirmed = tick?.confirmed || '—'
        const utilLed =
          confirmed === 'util_congestion' || String(confirmed).toLowerCase().includes('util')
        const conf =
          tick?.confidence != null && Number.isFinite(tick.confidence)
            ? tick.confidence.toFixed(2)
            : null
        const eta =
          tick?.eta_minutes != null && Number.isFinite(tick.eta_minutes)
            ? `${tick.eta_minutes}m`
            : null
        const rtt = liveRtt(site)
        // When no predictive ETA, show live GRE RTT so the strip is never blank
        const etaDisplay =
          eta ?? (rtt != null ? `${rtt.toFixed(1)}ms` : null)
        const etaTitle = eta
          ? utilLed
            ? 'Predictive minutes to HTB ceiling (soft util gate)'
            : 'Predictive minutes to hard SLA breach'
          : rtt != null
            ? 'Live GRE RTT (no breach ETA)'
            : undefined

        return (
          <article key={site.id} className={`deca-fleet-site tone-${tone}`}>
            <div className="deca-fleet-top">
              <span className={`deca-dot tone-${tone}`} />
              <h3>{site.name}</h3>
              <span className="deca-fleet-class">{CLASS_LABEL[site.mission_class] || site.mission_class}</span>
            </div>
            <p className="deca-fleet-role">{site.role}</p>
            <dl className="deca-fleet-metrics">
              <div>
                <dt>State</dt>
                <dd className={confirmed !== 'healthy' && confirmed !== '—' ? 'is-alert' : ''}>
                  {confirmed}
                </dd>
              </div>
              <div>
                <dt>Conf</dt>
                <dd title={conf ? 'SLA headroom / model confidence' : undefined}>
                  {conf ?? '—'}
                </dd>
              </div>
              <div>
                <dt>{eta ? 'ETA' : rtt != null ? 'RTT' : 'ETA'}</dt>
                <dd title={etaTitle}>{etaDisplay ?? '—'}</dd>
              </div>
            </dl>
            {site.hosts?.length ? (
              <p className="deca-fleet-host">{site.hosts.join(', ')}</p>
            ) : null}
          </article>
        )
      })}
    </section>
  )
}
