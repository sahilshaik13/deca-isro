'use client'

import { useMemo } from 'react'
import type { AlertRow, FleetSite, MissionState } from '@/lib/api'

function plainClass(cls: string | null, urgencyClockKind?: string | null) {
  if (!cls) return 'Unknown issue'
  if (cls === 'congestion_breach' && urgencyClockKind === 'soft_ceiling') {
    return 'Link filling up — about to hit capacity'
  }
  const map: Record<string, string> = {
    congestion_breach: 'Congestion — mission traffic at risk',
    tunnel_degradation: 'Primary path degrading (latency / loss)',
    bgp_route_flap: 'Routing unstable — paths flapping',
    vrf_leakage: 'Network isolation broken',
    policy_drift: 'Traffic policy drifted from the plan',
    advisory_raise: 'Early warning',
    advisory_clear: 'Warning cleared',
    confirmed_raise: 'Confirmed problem',
    confirmed_clear: 'Problem cleared',
    bgp_mild: 'Mild routing instability',
    physical_path_degradation: 'Physical / weather path degradation',
  }
  return map[cls] || cls.replace(/_/g, ' ')
}

function isActionable(a: AlertRow) {
  if (a.status !== 'active') return false
  if (!a.class || ['healthy', 'advisory_clear', 'confirmed_clear'].includes(a.class)) return false
  return (
    a.event === 'confirmed_raise' ||
    a.event === 'advisory_raise' ||
    ['congestion_breach', 'tunnel_degradation', 'bgp_route_flap', 'vrf_leakage', 'policy_drift'].includes(
      a.class,
    )
  )
}

function uniq(items: string[]) {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of items) {
    const s = raw.trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

/** Plain-language concerns for Decide — jury-readable first. */
function alertConcerns(a: AlertRow): string[] {
  const p = a.payload || {}
  const fromPayload = Array.isArray(p.concerns)
    ? (p.concerns as unknown[]).map((c) => String(c))
    : []
  if (fromPayload.length > 0) return uniq(fromPayload)

  const out: string[] = []
  const rc = String(p.root_cause || '').toLowerCase()
  const cls = a.class || ''
  const clockKind = String(p.urgency_clock_kind || '')
  const leadHead = String(p.urgency_lead_head || '')
  const utilLed =
    clockKind === 'soft_ceiling' ||
    leadHead === 'util' ||
    rc === 'util_congestion' ||
    (cls === 'congestion_breach' && p.eta_util_minutes != null && p.eta_loss_minutes == null)

  if (p.rogue_ce || p.victim_ce || rc === 'ce_sla_conflict') {
    out.push(
      `A lower-priority site (${String(p.rogue_ce || 'rogue')}) is crowding out critical site ${String(p.victim_ce || 'mission')}`,
    )
    out.push('Critical (Gold) traffic must not be starved — Approve backup now')
  } else if (cls === 'tunnel_degradation' || rc.includes('loss') || rc.includes('physical')) {
    out.push('Mission link is getting worse (latency / loss climbing)')
    if (p.eta_loss_minutes != null) {
      out.push(`About ${String(p.eta_loss_minutes)} min until service breaks the SLA`)
    }
    out.push('Approve switches to the backup path before the outage')
  } else if (utilLed) {
    out.push('The link is filling up — capacity limit approaching')
    if (p.eta_util_minutes != null) {
      out.push(`About ${String(p.eta_util_minutes)} min until the ceiling`)
    }
    out.push('Approve before shared headroom collapses')
  } else if (cls === 'congestion_breach' || rc.includes('cpu') || rc.includes('crypto')) {
    out.push('Router CPU / crypto overloaded — encrypted mission traffic may stall')
    out.push('Critical and payload traffic share this stressed router')
  } else if (cls === 'bgp_route_flap' || rc.includes('flap') || rc.includes('route')) {
    out.push('Routes keep changing — sites may briefly lose the preferred path')
    out.push('Approve a stable backup while routing settles')
  } else if (cls === 'policy_drift') {
    out.push('Configured traffic priority no longer matches what the edge is doing')
  } else if (cls === 'vrf_leakage') {
    out.push('Mission and admin networks may be leaking into each other')
  } else {
    out.push('Predicted SLA risk on the primary path — Approve backup before the window closes')
  }

  if (p.severity) out.push(`Severity ${String(p.severity)} — human Approve required`)
  return uniq(out)
}

function fabricConcerns(mission: MissionState | null, sites: FleetSite[]): string[] {
  const out: string[] = []
  if (mission?.conflict && mission.ttc_wanted !== mission.payload_wanted) {
    out.push(
      `Priority conflict: TT&C wants ${mission.ttc_wanted || '?'} but Payload wants ${mission.payload_wanted || '?'} — TT&C wins`,
    )
  }
  if (mission?.human_override) {
    out.push(`Operator holding path on ${mission.human_override} (auto-steer paused)`)
  }
  for (const s of sites) {
    const conf = s.hosts_state?.[0]?.confirmed
    if (!conf || conf === 'healthy' || conf === '—' || conf === 'none') continue
    if (
      mission?.conflict &&
      mission.ttc_wanted !== mission.payload_wanted &&
      conf === 'tunnel_degradation' &&
      s.mission_class !== 'ttc'
    ) {
      continue
    }
    out.push(`${s.name}: ${plainClass(conf)}`)
  }
  return uniq(out).slice(0, 6)
}

export default function AlertRail({
  alerts,
  actionBusy,
  onApprove,
  onReject,
  activePath,
  mission = null,
  sites = [],
}: {
  alerts: AlertRow[]
  actionBusy: number | null
  onApprove: (id: number, path?: string) => void
  onReject: (id: number) => void
  activePath: string | null
  mission?: MissionState | null
  sites?: FleetSite[]
}) {
  const actionable = alerts.filter(isActionable)
  const backup = activePath === 'eth0' ? 'gre' : 'eth0'
  const liveConcerns = useMemo(
    () => fabricConcerns(mission, sites),
    [mission, sites],
  )

  return (
    <section className="deca-panel deca-decision">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">
            <span className="deca-ps13-tag deca-ps13-tag-q2">Decide</span> What to do
          </h2>
          <p className="deca-section-sub">
            When the model predicts a problem, Approve moves traffic to the backup path.
            Reject only records that you declined.
          </p>
        </div>
        <span className="deca-count">{actionable.length}</span>
      </div>

      {liveConcerns.length > 0 ? (
        <div className="deca-concerns is-live" aria-label="Live fabric concerns">
          <p className="deca-concerns-title">What the network is saying now</p>
          <ul>
            {liveConcerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {actionable.length === 0 ? (
        <div className="deca-empty">
          <p>No decision needed yet.</p>
          <p className="text-[var(--deca-mute)] text-xs mt-1">
            Click a fault under Demo controls. A card will appear here with the prediction.
            Approve steers to backup and stops the fault; Reject declines the steer
            and also stops the inject. Either way the path settles back to healthy
            naturally (graphs cool down) — it does not snap idle instantly.
          </p>
        </div>
      ) : (
        <ul className="deca-alert-list">
          {actionable.slice(0, 10).map((a) => {
            const concerns = alertConcerns(a)
            return (
              <li key={a.id} className="deca-alert">
                <div className="deca-alert-head flex flex-col gap-1 mb-2">
                  {(() => {
                    const md = (a.payload?.model_detection || null) as Record<string, unknown> | null
                    const classes = Array.isArray(md?.top_classes) ? (md!.top_classes as Array<{severity?: string, name?: string, proba?: number}>) : []
                    const topClass = classes.length > 0 ? classes[0] : null
                    
                    const rawCls = topClass?.name || a.class || ''
                    const title = topClass?.name ? plainClass(rawCls) : ((a.payload?.title as string) || plainClass(rawCls, a.payload?.urgency_clock_kind as string | undefined))
                    
                    // Format confidence
                    let confStr = '?'
                    if (topClass?.proba != null) {
                      confStr = (topClass.proba * 100).toFixed(0)
                    } else if (a.confidence != null) {
                      confStr = (a.confidence * 100).toFixed(0)
                    }

                    // Format severity
                    const severity = topClass?.severity || md?.severity || a.payload?.severity
                    const sevSuffix = severity ? ` (${severity})` : ''

                    return (
                      <>
                        <p className="font-bold text-[14px]">
                          Predicted: {title}
                          {sevSuffix}
                        </p>
                        <p className="text-[13px] text-[var(--deca-warn)] font-medium">
                          {a.eta != null
                            ? `About ${a.eta} min until service impact · model ${confStr}% sure`
                            : `Model ${confStr}% sure · timing unknown`}
                        </p>
                      </>
                    )
                  })()}
                </div>

                <div className="deca-alert-actions mt-3 mb-3 flex items-center gap-3">
                  <button
                    type="button"
                    disabled={actionBusy === a.id}
                    onClick={() => onApprove(a.id, backup)}
                    className="deca-btn deca-btn-primary"
                  >
                    {actionBusy === a.id ? 'Switching…' : 'Approve backup'}
                  </button>
                  <button
                    type="button"
                    disabled={actionBusy === a.id}
                    onClick={() => onReject(a.id)}
                    className="deca-btn"
                  >
                    Reject
                  </button>
                  <span className="text-[11px] text-[var(--deca-mute)] leading-tight flex-1">
                    Moves traffic to {backup === 'eth0' ? 'backup (eth0)' : 'primary (GRE)'} and stops the fault
                  </span>
                </div>

                <div className="mt-2 text-xs text-[var(--deca-mute)] font-mono">
                  Ref ID: {a.id} — see Copilot for details
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
