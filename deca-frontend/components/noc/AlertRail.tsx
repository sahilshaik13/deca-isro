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

                <details className="group">
                  <summary className="text-xs cursor-pointer text-[var(--deca-link)] hover:underline select-none font-medium mb-2">
                    Inspect trace & metrics
                  </summary>
                  <div className="pt-3 border-t border-[var(--deca-border)] space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="deca-alert-event">Event: {a.event || 'event'}</span>
                    </div>

                    {a.payload?.summary ? (
                      <p className="deca-alert-hint">{String(a.payload.summary)}</p>
                    ) : null}

                    {concerns.length > 0 ? (
                      <div className="deca-concerns" aria-label="Alert concerns">
                        <p className="deca-concerns-title">Why this matters</p>
                        <ul>
                          {concerns.map((c) => (
                            <li key={c}>{c}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {a.payload?.root_cause ? (
                      <p className="deca-alert-hint">
                        <span className="text-[var(--deca-mute)]">Q2 · </span>
                        {String(a.payload.root_cause)}
                        {a.payload.severity ? ` · sev ${String(a.payload.severity)}` : ''}
                      </p>
                    ) : null}

                    {(() => {
                      const arb =
                        (a.payload?.arbitration as Record<string, unknown> | undefined) ||
                        (a.payload as Record<string, unknown> | undefined)
                      const heads = (arb?.firing_tti_heads ||
                        a.payload?.firing_tti_heads) as unknown
                      const compound = Boolean(
                        arb?.compound_suspected ?? a.payload?.compound_suspected,
                      )
                      const list = Array.isArray(heads)
                        ? heads.map((h) => String(h))
                        : []
                      if (!compound && list.length === 0) return null
                      return (
                        <div className="deca-alert-hint rounded border border-[var(--deca-warn)]/40 bg-[var(--deca-warn)]/5 p-2">
                          <p className="text-[10px] uppercase tracking-wide text-[var(--deca-warn)] mb-1 font-bold">
                            Multi-head arbitration
                            {compound ? ' · compound suspected' : ''}
                          </p>
                          {list.length > 0 ? (
                            <p className="text-[11px] font-mono">
                              firing_tti_heads: {list.join(' · ')}
                            </p>
                          ) : (
                            <p className="text-[11px] text-[var(--deca-mute)]">
                              compound_suspected (heads not listed)
                            </p>
                          )}
                        </div>
                      )
                    })()}

                    {(() => {
                      const md = (a.payload?.model_detection || null) as Record<string, unknown> | null
                      if (!md) return null
                      const signals = Array.isArray(md.top_signals)
                        ? (md.top_signals as Array<{ name?: string; value?: number }>)
                        : []
                      const classes = Array.isArray(md.top_classes)
                        ? (md.top_classes as Array<{
                            severity?: string
                            name?: string
                            proba?: number
                          }>)
                        : []
                      return (
                        <div className="deca-alert-hint rounded border border-[var(--deca-border)] bg-[var(--deca-panel-2,#0f172a)]/50 p-2">
                          <p className="text-[10px] uppercase tracking-wide text-[var(--deca-mute)] mb-1 flex items-center gap-1.5 font-bold">
                            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-purple-400"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M9 13a4.5 4.5 0 0 0 3-4"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M14.6 13.4a4.5 4.5 0 0 0 3.2-3.2"/><path d="M15 19a4 4 0 0 1-2.967-1.516"/></svg>
                            Q2 Inference Trace (Glassbox)
                            {md.ok === false ? ' · unavailable' : ''}
                          </p>
                          {md.explanation ? (
                            <p className="text-xs leading-relaxed mb-1.5">
                              {String(md.explanation)}
                            </p>
                          ) : null}
                          {md.ok !== false ? (
                            <p className="text-[11px] font-mono text-[var(--deca-mute)] mb-1">
                              sev {String(md.severity || a.payload?.severity || '—')}
                              {md.q2_confidence != null
                                ? ` · p=${Number(md.q2_confidence).toFixed(2)}`
                                : ''}
                              {md.matches_demo_fault != null
                                ? ` · demo-match ${md.matches_demo_fault ? 'yes' : 'no'}`
                                : ''}
                              {md.samples != null ? ` · n=${String(md.samples)}` : ''}
                            </p>
                          ) : (
                            <p className="text-[11px] text-[var(--deca-mute)]">
                              {String(md.error || 'detect failed')} — seed still actionable
                            </p>
                          )}
                          {signals.length > 0 ? (
                            <ul className="mt-1 text-[11px] font-mono space-y-0.5">
                              {signals.slice(0, 5).map((s) => (
                                <li key={String(s.name)}>
                                  {String(s.name)} ={' '}
                                  {s.value != null && Number.isFinite(Number(s.value))
                                    ? Number(s.value).toFixed(3)
                                    : '—'}
                                </li>
                              ))}
                            </ul>
                          ) : null}
                          {classes.length > 0 ? (
                            <p className="mt-1 text-[10px] text-[var(--deca-mute)] font-mono">
                              top:{' '}
                              {classes
                                .slice(0, 3)
                                .map(
                                  (c) =>
                                    `${c.severity || '?'} ${(Number(c.proba) * 100).toFixed(0)}%`,
                                )
                                .join(' · ')}
                            </p>
                          ) : null}
                        </div>
                      )
                    })()}

                    {a.payload?.rogue_ce || a.payload?.victim_ce ? (
                      <p className="deca-alert-hint text-xs">
                        <span className="text-[var(--deca-mute)]">CE SLA conflict · </span>
                        rogue{' '}
                        <span className="font-mono">
                          {String(a.payload.rogue_ce || '—')}
                          {a.payload.rogue_sla ? ` (${String(a.payload.rogue_sla)})` : ''}
                        </span>
                        {' → '}
                        victim{' '}
                        <span className="font-mono">
                          {String(a.payload.victim_ce || '—')}
                          {a.payload.victim_sla ? ` (${String(a.payload.victim_sla)})` : ''}
                        </span>
                      </p>
                    ) : null}

                    <dl className="deca-alert-meta">
                      <div>
                        <dt>Site / scope</dt>
                        <dd>{a.host || '—'}</dd>
                      </div>
                      <div>
                        <dt>Confidence</dt>
                        <dd title="Q2 class probability blended with ETA urgency (PS13-O3.3)">
                          {a.confidence != null ? a.confidence.toFixed(3) : '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>
                          {a.payload?.urgency_clock_kind === 'soft_ceiling'
                            ? 'ETA (ceiling)'
                            : 'ETA (Q1 SLA)'}
                        </dt>
                        <dd
                          title={
                            a.payload?.urgency_clock_kind === 'soft_ceiling'
                              ? 'Minutes to configured HTB ceiling (soft util gate)'
                              : 'Minutes to hard SLA breach (lat/loss/jitter)'
                          }
                        >
                          {a.eta != null ? `${a.eta} min` : '—'}
                        </dd>
                      </div>
                    </dl>

                    {a.payload?.eta_loss_minutes != null ? (
                      <p className="deca-alert-hint text-xs">
                        ETA loss SLA (Q1-loss):{' '}
                        <span className="font-mono">{String(a.payload.eta_loss_minutes)} min</span>
                      </p>
                    ) : null}
                    <p className="deca-alert-hint">
                      Approving will ask the controller to force underlay to{' '}
                      <strong className="font-mono">{backup}</strong> (backup of current{' '}
                      <span className="font-mono">{activePath || 'gre'}</span>), then audit the action.
                    </p>
                  </div>
                </details>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
