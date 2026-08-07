'use client'

import { useMemo, useState } from 'react'
import { Check, AlertTriangle, Radio } from 'lucide-react'
import type { AlertRow } from '@/lib/api'
import type { CopilotData } from '@/lib/telemetry-context'

interface ModelDetection {
  ok?: boolean
  severity?: string | null
  q2_confidence?: number | null
  eta_minutes?: number | null
  eta_source?: string | null
  raise?: boolean
  explanation?: string | null
  matches_demo_fault?: boolean | null
}

interface CopilotTerminalProps {
  isAnomaly: boolean
  copilotResponse: CopilotData
  loading: boolean
  source: string
  /** Fallback: build explanation from open Decide cards when dashboard copilot is idle. */
  alerts?: AlertRow[]
  /** Live Q1/Q2 oneshot from fault demo — preferred over inject button name. */
  modelDetection?: ModelDetection | null
  faultPhase?: string | null
}

const IDLE_ROOT = 'Monitoring live telemetry — no anomaly flagged.'

const PLAIN: Record<string, string> = {
  congestion_breach: 'Congestion — mission traffic at risk',
  tunnel_degradation: 'Primary path degrading (latency / loss)',
  bgp_route_flap: 'Routing unstable — paths flapping',
  vrf_leakage: 'Network isolation broken',
  policy_drift: 'Traffic policy drifted from the plan',
}

function isActionableAlert(a: AlertRow) {
  if (a.status !== 'active') return false
  const p = a.payload || {}
  if (p.preemption || p.noc_demo_fault) return true
  return Boolean(
    a.class &&
      !['healthy', 'advisory_clear', 'confirmed_clear'].includes(a.class) &&
      (a.event === 'confirmed_raise' ||
        a.event === 'advisory_raise' ||
        [
          'congestion_breach',
          'tunnel_degradation',
          'bgp_route_flap',
          'vrf_leakage',
          'policy_drift',
        ].includes(a.class)),
  )
}

function fromModelDetection(md: ModelDetection | null | undefined): CopilotData | null {
  if (!md?.ok) return null
  const sev = String(md.severity || '0')
  const raised = Boolean(md.raise) || (sev !== '0' && sev !== '')
  if (!raised) return null

  const bits = [`Model scores: Q2 severity ${sev}`]
  if (md.q2_confidence != null) bits[0] += ` (p=${Number(md.q2_confidence).toFixed(2)})`
  if (md.eta_minutes != null) bits.push(`Q1 TTI ≈ ${Number(md.eta_minutes).toFixed(2)} min`)
  if (md.eta_source) bits.push(`(${md.eta_source})`)
  if (md.explanation) bits.push(String(md.explanation))
  bits.push('Decide / Q3 ground on these scores — not the inject button name.')

  return {
    root_cause: bits.join(' '),
    runbook_steps: [
      'Confirm live Prom matches the model fingerprint',
      'Read Decide severity / ETA from Q1+Q2',
      'Click Approve backup to steer and stop the inject',
    ],
    mitigation_checklist: [
      'Approve backup on the Decide card',
      'Confirm the path badge updates after Approve',
      'Confirm Decide / Copilot return to idle',
    ],
  }
}

function fromAlerts(alerts: AlertRow[]): CopilotData | null {
  const a = alerts.find(isActionableAlert)
  if (!a) return null

  const p = a.payload || {}
  const q3 = typeof p.q3_nlp === 'string' ? p.q3_nlp.trim() : ''
  const title =
    (typeof p.title === 'string' && p.title) ||
    PLAIN[a.class || ''] ||
    (a.class || 'Network risk').replace(/_/g, ' ')
  const summary = typeof p.summary === 'string' ? p.summary.trim() : ''
  const root = typeof p.root_cause === 'string' ? p.root_cause.replace(/_/g, ' ') : ''
  const eta = a.eta ?? (typeof p.eta_minutes === 'number' ? p.eta_minutes : null)
  const md = (p.model_detection || null) as ModelDetection | null

  let root_cause = q3
  if (!root_cause) {
    const bits = [title]
    if (root) bits.push(`Model class: ${root}.`)
    if (md?.severity) {
      bits.push(`Q2 severity=${md.severity} (p=${md.q2_confidence ?? 'n/a'}).`)
    }
    if (summary) bits.push(summary)
    if (eta != null) bits.push(`Q1 predicted impact in about ${Number(eta).toFixed(1)} minutes.`)
    bits.push('Next step: Approve backup on the Decide card (or wait for auto-heal).')
    root_cause = bits.join(' ')
  }

  const runbook_steps: string[] = [
    'Confirm live metrics match the model class',
    'Read “why this matters” on the Decide card (Q1 ETA / Q2 severity)',
    'Click Approve backup to steer and stop the inject',
  ]
  const mitigation_checklist: string[] = [
    'Approve backup on Decide',
    'Confirm path / underlay badge updates',
    'Confirm alerts clear after steer or auto-heal',
  ]
  const actions = Array.isArray(p.recommended_actions) ? p.recommended_actions : []
  for (const item of actions) {
    if (typeof item === 'string' && item) mitigation_checklist.unshift(item)
    else if (item && typeof item === 'object') {
      const label =
        (item as { label?: string; action?: string }).label ||
        (item as { action?: string }).action
      if (label) mitigation_checklist.unshift(String(label))
    }
  }
  const concerns = Array.isArray(p.concerns) ? p.concerns : []
  for (const c of concerns.slice(0, 4)) {
    if (c) runbook_steps.push(String(c))
  }

  return { root_cause, runbook_steps, mitigation_checklist: mitigation_checklist.slice(0, 6) }
}

export default function CopilotTerminal({
  isAnomaly,
  copilotResponse,
  loading,
  source,
  alerts = [],
  modelDetection = null,
  faultPhase = null,
}: CopilotTerminalProps) {
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({})

  const effective = useMemo(() => {
    const idle =
      !copilotResponse.root_cause ||
      copilotResponse.root_cause === IDLE_ROOT ||
      copilotResponse.root_cause.toLowerCase().includes('no anomaly flagged')
    if (!idle && (copilotResponse.runbook_steps?.length || copilotResponse.root_cause)) {
      return copilotResponse
    }
    return fromAlerts(alerts) || fromModelDetection(modelDetection) || copilotResponse
  }, [copilotResponse, alerts, modelDetection])

  const modelReady = Boolean(fromModelDetection(modelDetection) || fromAlerts(alerts))
  const explaining =
    (isAnomaly && modelReady) ||
    modelReady ||
    (Boolean(effective.root_cause) &&
      effective.root_cause !== IDLE_ROOT &&
      !effective.root_cause.toLowerCase().includes('no anomaly flagged'))

  const waitingOnModel =
    !explaining &&
    Boolean(faultPhase) &&
    ['injecting', 'seeded', 'collapsing'].includes(String(faultPhase))

  const toggleCheck = (index: number) => {
    setCheckedItems((prev) => ({ ...prev, [index]: !prev[index] }))
  }

  if (loading) {
    return (
      <section className="deca-panel">
        <h2 className="deca-section-title">
          <span className="deca-ps13-tag deca-ps13-tag-q3">Explain</span> Copilot
        </h2>
        <div className="mt-3 min-h-48 animate-pulse bg-[var(--deca-panel-2)] border border-[var(--deca-line)]" />
      </section>
    )
  }

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">
            <span className="deca-ps13-tag deca-ps13-tag-q3">Explain</span> Copilot
          </h2>
          <p className="deca-section-sub">
            Plain-English from Q1/Q2 model scores (and Q3 once Decide raises)
          </p>
        </div>
      </div>

      <div
        className={`rounded border p-4 space-y-4 min-h-48 ${
          explaining
            ? 'bg-[var(--deca-panel-2)] border-[var(--deca-warn)]/40'
            : 'bg-[var(--deca-panel-2)] border-[var(--deca-line)]'
        }`}
      >
        <div className="flex items-center gap-2 text-xs font-mono text-[var(--deca-mute)]">
          <div
            className={`w-2.5 h-2.5 rounded-full ${
              explaining
                ? 'bg-[var(--deca-warn)] animate-pulse'
                : waitingOnModel
                  ? 'bg-[var(--deca-warn)]/60 animate-pulse'
                  : 'bg-[var(--deca-ok)]'
            }`}
          />
          {explaining
            ? 'Explaining from model / Decide'
            : waitingOnModel
              ? 'Inject live — waiting for Q1/Q2 scores'
              : 'Waiting for a prediction'}{' '}
          · {source}
        </div>

        {!explaining ? (
          <div className="space-y-3 py-2">
            <div className="flex items-start gap-3 text-[var(--deca-mute)]">
              <Radio className="w-4 h-4 text-[var(--deca-ok)] mt-0.5 shrink-0" />
              <p className="font-mono text-sm leading-relaxed">
                {waitingOnModel
                  ? 'Fault inject is running, but Copilot stays quiet until the model classifies the Prom window (Q2) and estimates TTI (Q1). Then it explains from those scores — not from the button you clicked.'
                  : 'Quiet until the model raises a Decide card. Then read the explanation here, and click Approve backup above — or wait and the fault collapses on its own.'}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="bg-rose-950/40 border border-rose-500/50 rounded p-3">
              <p className="text-rose-300 font-mono text-sm font-semibold flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                Model flagged a problem — next step is Approve backup (or wait to auto-heal)
              </p>
            </div>

            {effective.root_cause && effective.root_cause !== IDLE_ROOT ? (
              <div className="space-y-2">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">What went wrong</h3>
                <p className="text-slate-300 font-mono text-sm leading-relaxed">
                  {effective.root_cause}
                </p>
              </div>
            ) : null}

            {effective.runbook_steps.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">
                  Checks an operator would run
                </h3>
                <ol className="space-y-1">
                  {effective.runbook_steps.map((step, idx) => (
                    <li key={idx} className="text-slate-300 font-mono text-xs leading-relaxed">
                      <span className="text-slate-500">{idx + 1}.</span> {step}
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}

            {effective.mitigation_checklist.length > 0 ? (
              <div className="space-y-2 pt-4 border-t border-slate-700">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">Suggested actions</h3>
                <div className="space-y-2">
                  {effective.mitigation_checklist.map((item, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => toggleCheck(idx)}
                      className={`flex items-center gap-2 w-full text-left p-2 rounded transition-colors ${
                        checkedItems[idx]
                          ? 'bg-emerald-950/40 border border-emerald-500/30'
                          : 'bg-slate-900/40 border border-slate-700/50 hover:border-slate-600/50'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center text-xs transition-colors ${
                          checkedItems[idx]
                            ? 'bg-emerald-500 border-emerald-500'
                            : 'border-slate-600 bg-transparent'
                        }`}
                      >
                        {checkedItems[idx] && <Check className="w-3 h-3 text-slate-950" />}
                      </div>
                      <span
                        className={`font-mono text-sm ${
                          checkedItems[idx] ? 'text-emerald-300 line-through' : 'text-slate-300'
                        }`}
                      >
                        {item}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}

        <div className="pt-4 border-t border-[var(--deca-line)]">
          <p className="text-[var(--deca-mute)] font-mono text-xs">
            ${' '}
            <span className="animate-pulse">
              {explaining
                ? 'explaining from Q1/Q2 / Decide…'
                : waitingOnModel
                  ? 'waiting on model scores…'
                  : 'streaming from backend…'}
            </span>
          </p>
        </div>
      </div>
    </section>
  )
}
