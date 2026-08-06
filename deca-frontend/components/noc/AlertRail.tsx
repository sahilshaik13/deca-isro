'use client'

import { useMemo } from 'react'
import type { AlertRow, FleetSite, MissionState } from '@/lib/api'

function plainClass(cls: string | null, urgencyClockKind?: string | null) {
  if (!cls) return 'Unknown issue'
  if (cls === 'congestion_breach' && urgencyClockKind === 'soft_ceiling') {
    return 'Approaching HTB ceiling'
  }
  const map: Record<string, string> = {
    congestion_breach: 'Congestion / hard-SLA risk',
    tunnel_degradation: 'Tunnel degradation',
    bgp_route_flap: 'BGP route flap',
    vrf_leakage: 'VRF leakage',
    policy_drift: 'Policy drift',
    advisory_raise: 'Advisory raise',
    advisory_clear: 'Advisory clear',
    confirmed_raise: 'Confirmed raise',
    confirmed_clear: 'Confirmed clear',
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

/** Per-alert concerns for Decide — SLA / CoS / rogue-victim / layer. */
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
      `Rogue ${String(p.rogue_ce || 'lower-SLA CE')}` +
        (p.rogue_sla ? ` (${String(p.rogue_sla)})` : '') +
        ` endangering victim ${String(p.victim_ce || 'higher-SLA CE')}` +
        (p.victim_sla ? ` (${String(p.victim_sla)})` : ''),
    )
    out.push('Gold / TT&C CoS must not be starved by Bronze surge on shared PE HTB')
    out.push('Q2 owns rogue vs organic; util Q1 only clocks approaching HTB ceiling')
  } else if (cls === 'tunnel_degradation' || rc.includes('loss') || rc.includes('physical')) {
    out.push('TT&C SLA at risk — ≤25 ms latency · ≤5 ms jitter · ≤0.1% loss')
    if (p.eta_loss_minutes != null) {
      out.push(`Payload / loss head ETA ≈ ${String(p.eta_loss_minutes)} min to breach`)
    }
    out.push('Mission gre-te underlay degrading — Gold CE availability threatened')
  } else if (utilLed) {
    out.push('Approaching configured HTB ceiling (soft util gate) — not hard TT&C SLA breach wording')
    if (p.eta_util_minutes != null) {
      out.push(`Util head ETA ≈ ${String(p.eta_util_minutes)} min to ceiling`)
    }
    out.push('TT&C (1:10) and Payload (1:15) share PE headroom — Approve before ceiling collapses')
  } else if (cls === 'congestion_breach' || rc.includes('cpu') || rc.includes('crypto')) {
    out.push('PE crypto / HTB headroom — IPsec + LLQ may stall')
    out.push('TT&C (1:10) and Payload (1:15) share the stressed PE')
  } else if (cls === 'bgp_route_flap' || rc.includes('flap') || rc.includes('route')) {
    out.push('Control-plane instability — vrf-mission routes oscillating')
    out.push('CE reachability and path preference may flip mid-flow')
  } else if (cls === 'policy_drift') {
    out.push('Policy / CoS drift vs edge contract (CE tier · PE HTB/VRF)')
  } else if (cls === 'vrf_leakage') {
    out.push('VRF leakage — mission vs admin separation at risk')
  } else {
    out.push('Predictive hard-SLA risk on preferred underlay — Approve before SLA window closes')
  }

  if (p.severity) out.push(`Q2 severity ${String(p.severity)} — HITL gate required`)
  return uniq(out)
}

function fabricConcerns(mission: MissionState | null, sites: FleetSite[]): string[] {
  const out: string[] = []
  if (mission?.conflict) {
    out.push(
      `Mission policy conflict — TT&C wants ${mission.ttc_wanted || '?'} · Payload wants ${mission.payload_wanted || '?'} → TT&C wins`,
    )
  }
  if (mission?.human_override) {
    out.push(`Human gate holding underlay → ${mission.human_override} (autonomy suspended)`)
  }
  for (const s of sites) {
    const conf = s.hosts_state?.[0]?.confirmed
    if (!conf || conf === 'healthy' || conf === '—' || conf === 'none') continue
    // Mission conflict is already one line — don't spam every Payload CE as degraded
    // when only TT&C has breached its tighter SLA.
    if (
      mission?.conflict &&
      conf === 'tunnel_degradation' &&
      s.mission_class !== 'ttc'
    ) {
      continue
    }
    out.push(`${s.name} (${s.mission_class}): ${conf}`)
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
          <h2 className="deca-section-title">Decide</h2>
          <p className="deca-section-sub">
            Analyzer proposals with <strong>SLA / CoS concerns</strong>.{' '}
            <strong>Approve</strong> steers underlay; <strong>Reject</strong> records only.
          </p>
        </div>
        <span className="deca-count">{actionable.length}</span>
      </div>

      {liveConcerns.length > 0 ? (
        <div className="deca-concerns is-live" aria-label="Live fabric concerns">
          <p className="deca-concerns-title">Live fabric concerns</p>
          <ul>
            {liveConcerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {actionable.length === 0 ? (
        <div className="deca-empty">
          <p>No open proposals for this run.</p>
          <p className="text-[var(--deca-mute)] text-xs mt-1">
            Click a Simple fault — Decide will name the respective SLA / CE concerns for Approve.
          </p>
        </div>
      ) : (
        <ul className="deca-alert-list">
          {actionable.slice(0, 10).map((a) => {
            const concerns = alertConcerns(a)
            return (
              <li key={a.id} className="deca-alert">
                <div className="deca-alert-head">
                  <p className="deca-alert-class">
                    {(a.payload?.title as string) ||
                      plainClass(a.class, a.payload?.urgency_clock_kind as string | undefined)}
                  </p>
                  <span className="deca-alert-event">{a.event || 'event'}</span>
                </div>
                {a.payload?.summary ? (
                  <p className="deca-alert-hint mb-2">{String(a.payload.summary)}</p>
                ) : null}

                {concerns.length > 0 ? (
                  <div className="deca-concerns" aria-label="Alert concerns">
                    <p className="deca-concerns-title">Concerns</p>
                    <ul>
                      {concerns.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {a.payload?.root_cause ? (
                  <p className="deca-alert-hint mb-2">
                    <span className="text-[var(--deca-mute)]">Q2 · </span>
                    {String(a.payload.root_cause)}
                    {a.payload.severity ? ` · sev ${String(a.payload.severity)}` : ''}
                  </p>
                ) : null}

                {(() => {
                  const md = (a.payload?.model_detection || null) as Record<
                    string,
                    unknown
                  > | null
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
                    <div className="deca-alert-hint mb-2 rounded border border-[var(--deca-border)] bg-[var(--deca-panel-2,#0f172a)]/50 p-2">
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
                  <p className="deca-alert-hint mb-2 text-xs">
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
                {a.payload?.q3_nlp ? (
                  <div className="deca-alert-hint mb-2 rounded border border-[var(--deca-border)] bg-[var(--deca-panel-2,#0f172a)]/40 p-2">
                    <p className="text-[10px] uppercase tracking-wide text-[var(--deca-mute)] mb-1 flex items-center gap-1.5 font-bold">
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
                      Q3 Copilot RAG Pipeline (Phi-3)
                    </p>
                    <p className="whitespace-pre-wrap text-xs leading-relaxed">
                      {String(a.payload.q3_nlp)}
                    </p>
                    {Array.isArray(a.payload.q3_sources) && a.payload.q3_sources.length > 0 ? (
                      <p className="mt-1 text-[10px] text-[var(--deca-mute)] font-mono">
                        LNC: {(a.payload.q3_sources as string[]).slice(0, 4).join(' · ')}
                      </p>
                    ) : null}
                  </div>
                ) : a.payload?.q3_pending ? (
                  <p className="deca-alert-hint mb-2 text-[var(--deca-mute)] text-xs italic">
                    Q3 explanation loading (math gate already live — Approve does not wait)…
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
                {Array.isArray(a.payload?.recommended_actions) &&
                (a.payload.recommended_actions as string[]).length > 0 ? (
                  <div className="deca-alert-hint mb-2">
                    <p className="text-[10px] uppercase tracking-wide text-[var(--deca-mute)] mb-1">
                      Playbook (ranked SOP candidates)
                    </p>
                    <ol className="list-decimal pl-4 text-xs space-y-0.5">
                      {(a.payload.recommended_actions as string[]).map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ol>
                  </div>
                ) : null}
                {a.payload?.path_asymmetry_detected ? (
                  <p className="deca-alert-hint mb-2 text-xs">
                    Path asymmetry:{' '}
                    <span className="font-mono">
                      GRE−eth0=
                      {a.payload.path_asymmetry_ms != null
                        ? `${Number(a.payload.path_asymmetry_ms) >= 0 ? '+' : ''}${a.payload.path_asymmetry_ms} ms`
                        : 'flagged'}
                    </span>
                  </p>
                ) : null}
                {(() => {
                  const arb = (a.payload?.arbitration || {}) as Record<string, unknown>
                  const firing = Array.isArray(arb.firing_tti_heads)
                    ? (arb.firing_tti_heads as { head?: string; eta_seconds?: number }[])
                    : []
                  const compound =
                    arb.compound_suspected === true ||
                    a.payload?.compound_suspected === true ||
                    firing.length > 1
                  if (!compound && firing.length === 0) return null
                  return (
                    <div className="deca-alert-hint mb-2">
                      <p className="text-[10px] uppercase tracking-wide text-[var(--deca-mute)] mb-1">
                        {compound ? 'Compound / multi-fault (arbitration)' : 'TTI heads firing'}
                      </p>
                      <p className="text-xs mb-1">
                        Primary why:{' '}
                        <span className="font-mono">
                          {String(arb.primary_severity || arb.primary_issue || a.class || '—')}
                        </span>
                        {arb.primary_confidence != null
                          ? ` · conf ${Number(arb.primary_confidence).toFixed(2)}`
                          : ''}
                        {' · '}
                        urgency = min ETA among heads
                      </p>
                      {firing.length > 0 ? (
                        <ul className="list-disc pl-4 text-xs space-y-0.5 font-mono">
                          {firing.map((h, i) => (
                            <li key={i}>
                              {String(h.head || '?')}: ETA{' '}
                              {h.eta_seconds != null
                                ? `${(Number(h.eta_seconds) / 60).toFixed(1)} min`
                                : '—'}
                              {i === 0 ? ' (leading clock)' : ''}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <p className="mt-1 text-[10px] text-[var(--deca-mute)]">
                        Playbook keys off primary Q2 class; quieter concurrent faults may be
                        under-ranked (honest compound limit). Cross-site: see blast radius below.
                      </p>
                    </div>
                  )
                })()}
                {Array.isArray(a.payload?.affected_scope) &&
                (a.payload.affected_scope as string[]).length > 0 ? (
                  <div className="deca-alert-hint mb-2">
                    <p className="text-[10px] uppercase tracking-wide text-[var(--deca-mute)] mb-1">
                      Affected scope (topology blast radius · other paths/sites)
                    </p>
                    <ul className="list-disc pl-4 text-xs space-y-0.5">
                      {(a.payload.affected_scope as string[]).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                    {Array.isArray(a.payload?.correlated_alert_ids) &&
                    (a.payload.correlated_alert_ids as number[]).length > 0 ? (
                      <p className="mt-1 text-[10px] text-[var(--deca-mute)] font-mono">
                        correlated: {(a.payload.correlated_alert_ids as number[]).join(', ')}
                        {a.payload.correlation_reason
                          ? ` — ${String(a.payload.correlation_reason)}`
                          : ''}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {a.payload?.eta_loss_minutes != null ? (
                  <p className="deca-alert-hint mb-2 text-xs">
                    ETA loss SLA (Q1-loss):{' '}
                    <span className="font-mono">{String(a.payload.eta_loss_minutes)} min</span>
                  </p>
                ) : null}
                <p className="deca-alert-hint">
                  Approving will ask the controller to force underlay to{' '}
                  <strong className="font-mono">{backup}</strong> (backup of current{' '}
                  <span className="font-mono">{activePath || 'gre'}</span>), then audit the action.
                </p>
                <div className="deca-alert-actions">
                  <button
                    type="button"
                    disabled={actionBusy === a.id}
                    onClick={() => onApprove(a.id, backup)}
                    className="deca-btn deca-btn-primary"
                  >
                    {actionBusy === a.id ? 'Steering…' : `Approve → ${backup}`}
                  </button>
                  <button
                    type="button"
                    disabled={actionBusy === a.id}
                    onClick={() => onReject(a.id)}
                    className="deca-btn"
                  >
                    Reject
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
