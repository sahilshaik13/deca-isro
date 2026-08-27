'use client'

import { useMemo, useState } from 'react'
import { Check, AlertTriangle, Radio } from 'lucide-react'
import type { AlertRow } from '@/lib/api'
import type { CopilotData } from '@/lib/telemetry-context'

export interface ExtendedCopilotData extends CopilotData {
  ref_id?: number
  metric_summary?: string[]
  headline?: string
  story?: string
  facts?: { label: string; value: string }[]
  technical?: string
}

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
  alerts?: AlertRow[]
  modelDetection?: ModelDetection | null
  faultPhase?: string | null
}

const IDLE_ROOT = 'Monitoring live telemetry — no anomaly flagged.'

const PLAIN_CLASS: Record<string, string> = {
  congestion_breach: 'Congestion — mission traffic at risk',
  tunnel_degradation: 'Primary path getting slower',
  bgp_route_flap: 'Routing unstable — paths flapping',
  vrf_leakage: 'Network isolation broken',
  policy_drift: 'Traffic policy drifted from the plan',
}

const PLAIN_SEV: Record<string, string> = {
  '1A': 'Early warning — GRE path is slowing',
  '1B': 'Critical — close to the 25 ms timing limit',
  '1C': 'Breach — timing limit already crossed or imminent',
  '2A': 'CPU strain — crypto/forwarding under load',
  '2B': 'Severe CPU stress — forwarding at risk',
  '3A': 'Mild BGP flap',
  '3B': 'Severe BGP flap',
  '4A': 'Packet loss climbing',
  '4B': 'Packet-loss SLA at risk',
  '5A': 'Link filling up',
  '5B': 'Capacity ceiling nearly hit',
  '6A': 'CE SLA pressure starting',
  '6B': 'CE SLA conflict — mission traffic crowded out',
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

/** Strip lab / inject wording — Copilot must read as live NOC, not a demo. */
function scrubOperatorVoice(text: string): string {
  return text
    .replace(/\b(lab\s+)?(fault\s+)?inject(ion|ed|ing|s)?\b/gi, 'event')
    .replace(/\bdemo\s+faults?\b/gi, 'path issue')
    .replace(/\bnoc_demo_fault\b/gi, '')
    .replace(/\binject_[a-z0-9_]+\.sh\b/gi, '')
    .replace(/\bNetEM\b/gi, 'path impairment')
    .replace(/\bhold window\b/gi, 'recovery window')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

/** Prefer structured Q3; otherwise keep short plain sentences only. */
function cleanOperatorText(raw: string): { headline?: string; story: string } {
  const text = scrubOperatorVoice((raw || '').trim())
  if (!text) return { story: '' }

  const headline = text.match(/HEADLINE:\s*(.+)/i)?.[1]?.trim()
  const storyBlock =
    text.match(/STORY:\s*([\s\S]+?)(?=\nNEXT:|\nWHY:|\nOPERATOR|$)/i)?.[1]?.trim() ||
    text.match(/IN_PLAIN_ENGLISH:\s*([\s\S]+?)(?=\nNEXT:|\nWHY:|\nOPERATOR|$)/i)?.[1]?.trim()

  if (headline || storyBlock) {
    return {
      headline: headline ? scrubOperatorVoice(headline) : undefined,
      story: scrubOperatorVoice(
        (storyBlock || text).replace(/\s+/g, ' ').trim().slice(0, 420),
      ),
    }
  }

  // Drop dense model traces / duplicate score lines from freeform dumps.
  const cleaned = text
    .replace(/Q2 \([^)]+\) classed[\s\S]*?(?=\.|$)/gi, '')
    .replace(/Live signals:[^.]*\./gi, '')
    .replace(/looking for:[^.]*\./gi, '')
    .replace(/eta_source=\S+/gi, '')
    .replace(/p=\d+\.\d+/gi, '')
    .replace(/\(p=[^)]+\)/gi, '')
    .replace(/\s+/g, ' ')
    .trim()

  const sentences = cleaned
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 12)
    .filter(
      (s) =>
        !/^Model scores/i.test(s) &&
        !/^Q1\+Q2:/i.test(s) &&
        !/^Trace detail/i.test(s) &&
        !/d2_e100/i.test(s) &&
        !/\binject/i.test(s) &&
        !/\bdemo fault/i.test(s),
    )

  const story = scrubOperatorVoice((sentences.slice(0, 3).join(' ') || cleaned).slice(0, 420))
  return { story }
}

function sevPlain(sev: string | null | undefined) {
  if (!sev || sev === '0') return null
  return PLAIN_SEV[sev] || `Severity ${sev}`
}

function buildBriefFromAlert(a: AlertRow): ExtendedCopilotData {
  const p = a.payload || {}
  const md = (p.model_detection || null) as ModelDetection | null
  const cls = a.class || ''
  const sev = String(md?.severity || p.severity || '').trim()
  const eta = a.eta ?? (typeof p.eta_minutes === 'number' ? p.eta_minutes : null)
  const conf =
    a.confidence != null
      ? a.confidence
      : md?.q2_confidence != null
        ? Number(md.q2_confidence)
        : null

  const signals = (p.contributing_signals || {}) as Record<string, number>
  const gre =
    typeof signals.latency_gre_ms === 'number'
      ? signals.latency_gre_ms
      : typeof p.q3_prom_snapshot?.latency_gre_ms === 'number'
        ? p.q3_prom_snapshot.latency_gre_ms
        : null

  const headline =
    PLAIN_CLASS[cls] ||
    sevPlain(sev) ||
    (typeof p.title === 'string' ? p.title.replace(/^Q1\+Q2:\s*/i, '') : null) ||
    'Network risk detected'

  const q3 = typeof p.q3_nlp === 'string' ? p.q3_nlp.trim() : ''
  const parsed = cleanOperatorText(q3)
  const fallbackStory = [
    sevPlain(sev) || 'The model sees the primary path degrading.',
    eta != null
      ? `About ${Number(eta).toFixed(1)} minutes left before the timing limit if nothing changes.`
      : null,
    'Approve backup to move mission traffic onto eth0, or wait for the primary path to recover.',
  ]
    .filter(Boolean)
    .join(' ')

  const storyRaw =
    parsed.story &&
    !/Q3 LLM unavailable|retrieve-only|No matching runbook/i.test(parsed.story)
      ? parsed.story
      : fallbackStory
  const story = scrubOperatorVoice(storyRaw)

  const facts: { label: string; value: string }[] = []
  if (a.host) facts.push({ label: 'Site', value: String(a.host) })
  if (sev && sev !== '0') {
    facts.push({ label: 'Severity', value: `${sev}${sevPlain(sev) ? ` — ${sevPlain(sev)}` : ''}` })
  }
  if (conf != null) facts.push({ label: 'Confidence', value: `${Math.round(Number(conf) * 100)}%` })
  if (eta != null) facts.push({ label: 'Time left', value: `~${Number(eta).toFixed(1)} min` })
  if (gre != null) facts.push({ label: 'GRE latency', value: `${Number(gre).toFixed(1)} ms` })
  if (p.rogue_ce || p.victim_ce) {
    facts.push({
      label: 'Conflict',
      value: `${p.rogue_ce || 'rogue'} crowding ${p.victim_ce || 'mission'}`,
    })
  }

  const runbook_steps = [
    'Glance at Live metrics — does GRE latency (or loss/CPU/flaps) match this story?',
    'On Decide, confirm severity and time-left look right.',
    'Click Approve backup to steer now — or wait for auto-heal after the hold.',
  ]

  // Keep a short operator checklist only — do not pull Decide playbook /
  // force_path wording into Copilot (that reads like an inject lab).
  const mitigation_checklist = [
    'Approve backup on the Decide card',
    'Confirm the path badge flips to backup / eth0',
    'Confirm Copilot and Decide go quiet after steer',
  ]

  const technical =
    typeof md?.explanation === 'string' && md.explanation.trim()
      ? scrubOperatorVoice(md.explanation.trim()).slice(0, 220)
      : undefined

  return {
    ref_id: a.id,
    headline: parsed.headline || headline,
    story,
    facts,
    technical,
    root_cause: story,
    metric_summary: facts.map((f) => `${f.label}: ${f.value}`),
    runbook_steps,
    mitigation_checklist: mitigation_checklist.slice(0, 5),
  }
}

function buildBriefFromModel(md: ModelDetection): ExtendedCopilotData | null {
  if (!md.ok) return null
  const sev = String(md.severity || '0').trim()
  const raised = Boolean(md.raise) || (sev !== '0' && sev !== '')
  if (!raised) return null

  const eta = md.eta_minutes
  const story = [
    sevPlain(sev) || 'Model sees a developing path problem.',
    eta != null
      ? `Roughly ${Number(eta).toFixed(1)} minutes until impact if the trend continues.`
      : null,
    'Open Decide when the card appears, then Approve backup or wait for auto-heal.',
  ]
    .filter(Boolean)
    .join(' ')

  const facts: { label: string; value: string }[] = []
  if (sev !== '0') facts.push({ label: 'Severity', value: sev })
  if (md.q2_confidence != null) {
    facts.push({ label: 'Confidence', value: `${Math.round(Number(md.q2_confidence) * 100)}%` })
  }
  if (eta != null) facts.push({ label: 'Time left', value: `~${Number(eta).toFixed(1)} min` })

  return {
    headline: sevPlain(sev) || 'Model raised a risk',
    story,
    facts,
    technical: md.explanation ? String(md.explanation).slice(0, 220) : undefined,
    root_cause: story,
    metric_summary: facts.map((f) => `${f.label}: ${f.value}`),
    runbook_steps: [
      'Wait for / open the Decide card from these scores',
      'Confirm Live metrics match the severity story',
      'Approve backup to steer, or wait for auto-heal',
    ],
    mitigation_checklist: [
      'Approve backup on Decide',
      'Confirm path badge updates',
      'Confirm Copilot returns to idle',
    ],
  }
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
  const [showTech, setShowTech] = useState(false)

  const effective = useMemo(() => {
    const alert = alerts.find(isActionableAlert)
    if (alert) return buildBriefFromAlert(alert)
    const fromMd = modelDetection ? buildBriefFromModel(modelDetection) : null
    if (fromMd) return fromMd

    const idle =
      !copilotResponse.root_cause ||
      copilotResponse.root_cause === IDLE_ROOT ||
      copilotResponse.root_cause.toLowerCase().includes('no anomaly flagged')
    if (idle) {
      return {
        root_cause: IDLE_ROOT,
        runbook_steps: [],
        mitigation_checklist: [],
        story: '',
        facts: [],
      } as ExtendedCopilotData
    }
    const parsed = cleanOperatorText(copilotResponse.root_cause)
    return {
      ...copilotResponse,
      headline: 'Operator briefing',
      story: parsed.story || copilotResponse.root_cause,
      facts: [],
    } as ExtendedCopilotData
  }, [copilotResponse, alerts, modelDetection])

  const explaining =
    Boolean(effective.story || (effective.root_cause && effective.root_cause !== IDLE_ROOT)) &&
    !(effective.root_cause || '').toLowerCase().includes('no anomaly flagged')

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
          <p className="deca-section-sub">Short operator briefing — not a raw model dump</p>
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
            ? 'Briefing ready'
            : waitingOnModel
              ? 'Watching telemetry — waiting for model scores'
              : 'Quiet'}{' '}
          · {source}
        </div>

        {!explaining ? (
          <div className="flex items-start gap-3 text-[var(--deca-mute)] py-2">
            <Radio className="w-4 h-4 text-[var(--deca-ok)] mt-0.5 shrink-0" />
            <p className="font-mono text-sm leading-relaxed">
              {waitingOnModel
                ? 'Telemetry is moving. Copilot stays quiet until the model names the problem and estimates time left — then this panel becomes a short operator brief.'
                : 'No active Decide card yet. When the model raises one, you will see a short story, a few facts, and what to click next.'}
            </p>
          </div>
        ) : (
          <>
            <div className="bg-rose-50 border border-rose-300 rounded p-3 space-y-1">
              <div className="flex justify-between items-start gap-2 flex-wrap">
                <p className="text-rose-800 font-semibold text-sm flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  {effective.headline || 'Action needed on Decide'}
                </p>
                {effective.ref_id ? (
                  <span className="text-rose-700 font-mono text-[0.65rem] border border-rose-300 px-2 py-0.5 rounded bg-white">
                    Decide #{effective.ref_id}
                  </span>
                ) : null}
              </div>
              <p className="text-rose-900/80 text-xs">
                Next step: Approve backup on the Decide card (or wait for auto-heal).
              </p>
            </div>

            {effective.story ? (
              <p className="text-[var(--deca-ink)] text-sm leading-relaxed">{effective.story}</p>
            ) : null}

            {effective.facts && effective.facts.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-[var(--deca-ink)] text-xs font-semibold uppercase tracking-wide">
                  At a glance
                </h3>
                <dl className="grid grid-cols-2 gap-2">
                  {effective.facts.map((f) => (
                    <div
                      key={f.label}
                      className="rounded border border-[var(--deca-line)] bg-white px-2.5 py-2"
                    >
                      <dt className="text-[0.65rem] uppercase tracking-wide text-[var(--deca-mute)]">
                        {f.label}
                      </dt>
                      <dd className="text-sm text-[var(--deca-ink)] mt-0.5 leading-snug">{f.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : null}

            {effective.runbook_steps.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-[var(--deca-ink)] text-xs font-semibold uppercase tracking-wide">
                  Quick checks
                </h3>
                <ol className="space-y-1.5">
                  {effective.runbook_steps.map((step, idx) => (
                    <li key={idx} className="text-[var(--deca-ink)] text-sm leading-relaxed flex gap-2">
                      <span className="text-[var(--deca-mute)] font-mono text-xs mt-0.5">{idx + 1}.</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}

            {effective.mitigation_checklist.length > 0 ? (
              <div className="space-y-2 pt-3 border-t border-[var(--deca-line)]">
                <h3 className="text-[var(--deca-ink)] text-xs font-semibold uppercase tracking-wide">
                  Do this
                </h3>
                <div className="space-y-2">
                  {effective.mitigation_checklist.map((item, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => toggleCheck(idx)}
                      className={`flex items-center gap-2 w-full text-left p-2 rounded transition-colors ${
                        checkedItems[idx]
                          ? 'bg-emerald-50 border border-emerald-300'
                          : 'bg-white border border-[var(--deca-line)] hover:border-[var(--deca-accent)]'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                          checkedItems[idx]
                            ? 'bg-emerald-500 border-emerald-500'
                            : 'border-[var(--deca-line)]'
                        }`}
                      >
                        {checkedItems[idx] ? <Check className="w-3 h-3 text-white" /> : null}
                      </div>
                      <span
                        className={`text-sm ${
                          checkedItems[idx]
                            ? 'text-[var(--deca-ok)] line-through'
                            : 'text-[var(--deca-ink)]'
                        }`}
                      >
                        {item}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {effective.technical ? (
              <div className="pt-2 border-t border-[var(--deca-line)]">
                <button
                  type="button"
                  className="text-xs text-[var(--deca-mute)] hover:text-[var(--deca-ink)]"
                  onClick={() => setShowTech((v) => !v)}
                >
                  {showTech ? 'Hide' : 'Show'} technical model note
                </button>
                {showTech ? (
                  <p className="mt-2 text-xs font-mono text-[var(--deca-mute)] leading-relaxed">
                    {effective.technical}
                  </p>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  )
}
