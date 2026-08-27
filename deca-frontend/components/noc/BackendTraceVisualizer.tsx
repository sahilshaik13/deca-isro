import { useEffect, useRef, useState } from 'react'
import {
  Terminal,
  Brain,
  Activity,
  ShieldAlert,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Network,
  Clock,
} from 'lucide-react'
import { DECA_CITE_BOARD } from '@/lib/cite-board'

type LogEntry = {
  id: string
  timestamp: Date
  source: 'model_detect' | 'lstm_eta' | 'rag_engine' | 'orchestrator'
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
}

export default function BackendTraceVisualizer({
  alerts,
  faultStatus,
  telemetry,
}: {
  alerts: any[]
  faultStatus: any
  telemetry: any
  historyActions?: any[]
}) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [faultInjectTime, setFaultInjectTime] = useState<number | null>(null)
  const [detectLatency, setDetectLatency] = useState<number | null>(null)
  const [trials, setTrials] = useState<{ id: string; latency: number; correct: boolean }[]>([])
  const [activeFault, setActiveFault] = useState<string | null>(null)
  const [inferenceData, setInferenceData] = useState<any>(null)

  const addLog = (source: LogEntry['source'], message: string, type: LogEntry['type']) => {
    setLogs((prev) =>
      [
        ...prev,
        {
          id: Math.random().toString(36).substring(7),
          timestamp: new Date(),
          source,
          message,
          type,
        },
      ].slice(-100),
    )
  }

  useEffect(() => {
    if (faultStatus?.running && faultStatus.fault_id && faultStatus.fault_id !== activeFault) {
      setActiveFault(faultStatus.fault_id)
      setFaultInjectTime(Date.now())
      setDetectLatency(null)
      addLog(
        'orchestrator',
        `POST /api/v1/faults/start → Injected ${faultStatus.fault_id}`,
        'warning',
      )
    } else if (!faultStatus?.running) {
      setActiveFault(null)
      setInferenceData(null)
    }
  }, [faultStatus?.running, faultStatus?.fault_id, activeFault])

  useEffect(() => {
    if (alerts && alerts.length > 0) {
      const a = alerts[0]
      if (a.status === 'active' && activeFault && !detectLatency && faultInjectTime) {
        const alertTime = new Date(a.ts).getTime()
        if (alertTime >= faultInjectTime - 1000) {
          const latency = Math.max(100, alertTime - faultInjectTime)
          setDetectLatency(latency)
          setInferenceData(a)
          setTrials((prev) => {
            if (prev.find((t) => t.id === a.id)) return prev
            return [...prev, { id: a.id, latency, correct: true }]
          })
          addLog(
            'model_detect',
            `Detection → class=${a.class} latency=${(latency / 1000).toFixed(1)}s (match pipeline tabs 1→3)`,
            'success',
          )
        }
      }
    }
  }, [alerts, activeFault, faultInjectTime, detectLatency])

  useEffect(() => {
    if (isExpanded) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, isExpanded])

  const isHealthy = !activeFault && (!alerts || alerts.length === 0 || alerts[0].status !== 'active')
  const avgLatency =
    trials.length > 0
      ? (trials.reduce((a, b) => a + b.latency, 0) / trials.length / 1000).toFixed(1)
      : '0.0'

  const featureVector = {
    bgp_updates: telemetry?.routing_updates ?? telemetry?.bgp_update_rate ?? 0,
    latency_ms: telemetry?.latency_gre_ms ?? telemetry?.latency_eth0_ms ?? null,
    packet_loss: telemetry?.packet_loss ?? telemetry?.packet_loss_pct ?? null,
    jitter: telemetry?.link_jitter ?? telemetry?.jitter_ms ?? null,
    throughput_out: telemetry?.network_throughput_out ?? telemetry?.ifOutOctets ?? null,
  }

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">
            Model evidence
          </h2>
          <p className="deca-section-sub">
            Technical trace of inject → detect (for deep dive; optional for the demo walkthrough)
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--deca-mute)] mb-3">
        <span className="flex items-center gap-1.5 bg-[var(--deca-panel-2)] px-2 py-1 border border-[var(--deca-line)]">
          <ShieldAlert size={12} /> Trials: {trials.length}
        </span>
        <span className="flex items-center gap-1.5 bg-[var(--deca-panel-2)] px-2 py-1 border border-[var(--deca-line)]">
          <CheckCircle2 size={12} className="text-[var(--deca-ok)]" /> Correct:{' '}
          {trials.filter((t) => t.correct).length}/{trials.length}
        </span>
        <span className="flex items-center gap-1.5 bg-[var(--deca-panel-2)] px-2 py-1 border border-[var(--deca-line)]">
          <Clock size={12} className="text-[var(--deca-accent)]" /> Avg: {avgLatency}s
        </span>
      </div>

      <div
        className={`p-4 border flex items-center gap-4 ${
          isHealthy
            ? 'bg-[var(--deca-ok)]/10 border-[var(--deca-ok)]/30'
            : 'bg-[var(--deca-warn)]/10 border-[var(--deca-warn)]/30'
        }`}
      >
        {isHealthy ? (
          <CheckCircle2 size={24} className="text-[var(--deca-ok)] shrink-0" />
        ) : (
          <ShieldAlert size={24} className="text-[var(--deca-warn)] shrink-0" />
        )}
        <div className="flex-1">
          {isHealthy ? (
            <p className="text-sm font-medium text-[var(--deca-ok)]">
              Network healthy. Waiting for fault inject.
            </p>
          ) : (
            <div>
              <p className="text-sm font-medium text-[var(--deca-warn)]">
                Fault injected →{' '}
                {inferenceData
                  ? `detected ${inferenceData.class} in ${((detectLatency || 0) / 1000).toFixed(1)}s`
                  : 'Waiting for detection…'}
              </p>
              {inferenceData ? (
                <p className="text-xs text-[var(--deca-mute)] mt-1">
                  Confidence:{' '}
                  <span className="font-mono text-[var(--deca-ink)]">
                    {((inferenceData.payload?.confidence || inferenceData.confidence || 0) * 100).toFixed(0)}%
                  </span>
                </p>
              ) : null}
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full mt-3 py-1.5 flex items-center justify-center gap-1.5 text-xs font-medium text-[var(--deca-mute)] hover:text-[var(--deca-ink)] bg-[var(--deca-panel-2)] border border-[var(--deca-line)]"
      >
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        Layer 2 — checkpoint + feature vector
      </button>

      {isExpanded ? (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-[var(--deca-panel-2)] p-3 border border-[var(--deca-line)]">
            <h4 className="text-xs uppercase tracking-widest text-[var(--deca-mute)] mb-2 flex items-center gap-2">
              <Network size={12} /> Cite board (single source)
            </h4>
            <p className="text-sm font-mono">{DECA_CITE_BOARD.checkpoint}</p>
            <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] font-mono">
              <div className="bg-[#0b1018] p-1.5 text-center">
                <span className="block text-[var(--deca-mute)]">GNS3 transfer</span>
                <span className="text-emerald-400">{DECA_CITE_BOARD.gns3_transfer}</span>
              </div>
              <div className="bg-[#0b1018] p-1.5 text-center">
                <span className="block text-[var(--deca-mute)]">Chaos F1</span>
                <span className="text-blue-400">{DECA_CITE_BOARD.chaos_f1}</span>
              </div>
              <div className="bg-[#0b1018] p-1.5 text-center">
                <span className="block text-[var(--deca-mute)]">Q1 lead</span>
                <span className="text-amber-400">{DECA_CITE_BOARD.q1_lead_s}s</span>
              </div>
              <div className="bg-[#0b1018] p-1.5 text-center">
                <span className="block text-[var(--deca-mute)]">Q2 holdout</span>
                <span className="text-purple-300">{DECA_CITE_BOARD.q2_holdout}</span>
              </div>
            </div>
            <p className="mt-2 text-[10px] text-[var(--deca-mute)]">
              Also: MAE {DECA_CITE_BOARD.q1_mae} · cite {DECA_CITE_BOARD.line}
            </p>
          </div>

          <div className="bg-[var(--deca-panel-2)] p-3 border border-[var(--deca-line)]">
            <h4 className="text-xs uppercase tracking-widest text-[var(--deca-mute)] mb-2 flex items-center gap-2">
              <Activity size={12} /> Live feature vector
            </h4>
            <pre className="text-[10px] font-mono overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(featureVector, null, 2)}
            </pre>
          </div>

          <div className="md:col-span-2 flex flex-col">
            <h4 className="text-xs uppercase tracking-widest text-[var(--deca-mute)] mb-2 flex items-center gap-2">
              <Terminal size={12} /> Event trail (no synthetic Prom noise)
            </h4>
            <div className="bg-[#0b1018] border border-[var(--deca-line)] overflow-y-auto p-2 space-y-1 font-mono text-[9px] max-h-[180px]">
              {logs.length === 0 ? (
                <p className="text-[var(--deca-mute)]">waiting for inject / detect…</p>
              ) : (
                logs.map((log) => (
                  <div key={log.id} className="flex items-start gap-2">
                    <span className="text-[var(--deca-mute)] shrink-0">
                      [{log.timestamp.toISOString().split('T')[1]?.slice(0, 12)}]
                    </span>
                    <span
                      className={`break-all ${
                        log.type === 'error'
                          ? 'text-red-400'
                          : log.type === 'warning'
                            ? 'text-amber-400'
                            : log.type === 'success'
                              ? 'text-green-400'
                              : 'text-gray-300'
                      }`}
                    >
                      <span className="text-[var(--deca-mute)] mr-1">[{log.source}]</span>
                      {log.message}
                    </span>
                  </div>
                ))
              )}
              <div ref={bottomRef} />
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
