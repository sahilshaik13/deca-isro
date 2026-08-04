'use client'

import type { MissionState } from '@/lib/api'

type Thr = {
  latency_ms?: number
  jitter_ms?: number
  loss_pct?: number
  dscp?: string
  phb?: string
  htb?: string
}

function PathChip({ label, path, winner }: { label: string; path?: string; winner?: boolean }) {
  return (
    <div className={`deca-qos-chip${winner ? ' is-winner' : ''}`}>
      <span className="deca-field-label">{label}</span>
      <strong className="font-mono">{path || '—'}</strong>
      {winner ? <em>wins conflicts</em> : null}
    </div>
  )
}

function slaLine(t?: Thr, fallback?: string) {
  if (!t?.latency_ms) return fallback || '—'
  return `≤${t.latency_ms} ms · ≤${t.jitter_ms} ms jit · ≤${t.loss_pct}% loss`
}

export default function MissionClasses({ mission }: { mission: MissionState | null }) {
  const thr = mission?.thresholds || {}
  const ttc = thr.ttc as Thr | undefined
  const payload = thr.payload as Thr | undefined
  const be = thr.be as Thr | undefined
  const hyst = thr.hysteresis as { enter_k?: number; exit_k?: number } | undefined
  const paths = thr.paths as
    | { preferred?: string; backup?: string; ospf_pref?: number; ospf_backup?: number }
    | undefined

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Mission policy</h2>
          <p className="deca-section-sub">
            AAR SLAs → LLQ/HTB → path steer. TT&amp;C preempts Payload on conflict; admin stays on
            eth0. Read-only catalog — Approve / override only.
          </p>
        </div>
      </div>

      <div className="deca-qos-paths">
        <PathChip label="Active underlay" path={mission?.active_path} />
        <PathChip label="TT&C wants" path={mission?.ttc_wanted} winner />
        <PathChip label="Payload wants" path={mission?.payload_wanted} />
      </div>

      <div className="deca-qos-table">
        <div className="deca-qos-row head">
          <span>Class</span>
          <span>Tag</span>
          <span>HTB</span>
          <span>AAR SLA</span>
        </div>
        <div className="deca-qos-row">
          <span className="name">TT&amp;C</span>
          <span>
            {ttc?.phb || 'CS4'} / {ttc?.dscp || '0x88'}
          </span>
          <span className="mono">{ttc?.htb || '1:10'} LLQ</span>
          <span className="mono">{slaLine(ttc, '≤25 · ≤5 · ≤0.1%')}</span>
        </div>
        <div className="deca-qos-row">
          <span className="name">Payload</span>
          <span>
            {payload?.phb || 'AF41'} / {payload?.dscp || '0x80'}
          </span>
          <span className="mono">{payload?.htb || '1:15'} 70%</span>
          <span className="mono">{slaLine(payload, '≤80 · ≤15 · ≤2%')}</span>
        </div>
        <div className="deca-qos-row">
          <span className="name">Admin / BE</span>
          <span>
            {be?.phb || 'BE'} / {be?.dscp || '0x00'}
          </span>
          <span className="mono">{be?.htb || '1:20'} scavenger</span>
          <span className="mono">vrf-admin · eth0 only</span>
        </div>
      </div>

      <ul className="deca-policy-notes">
        <li>
          <strong>ESP</strong> — zero-trust IPsec; <code>copy_dscp=out</code>; TT&amp;C fail-closed if
          crypto fails on backup.
        </li>
        <li>
          <strong>Paths</strong> — preferred{' '}
          <code>{paths?.preferred || 'gre-te-core'}</code> (OSPF {paths?.ospf_pref ?? 5}) · backup{' '}
          <code>{paths?.backup || 'eth0'}</code> (OSPF {paths?.ospf_backup ?? 50}).
        </li>
        <li>
          <strong>Anti-flap</strong> — failover after{' '}
          <strong>{hyst?.enter_k ?? 3}</strong> bad probes; return after{' '}
          <strong>{hyst?.exit_k ?? 10}</strong> clean probes.
        </li>
        <li>
          <strong>HITL</strong> — Approve required for AI steers (T_breach &lt; 180s warn; 90s
          timeout). Manual override supremacy via <code>POST /action</code>.
        </li>
        <li>
          <strong>Underlay</strong> — <code>vrf-mission</code> RT 65001:100 · single CORE · GRE legs
          BSID 40001/40002 · air-gapped Prom/LLM.
        </li>
      </ul>
    </section>
  )
}
