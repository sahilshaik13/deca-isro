import { useEffect, useRef, useState } from 'react'
import { Terminal, Database, Brain, Activity, Zap } from 'lucide-react'

type LogEntry = {
  id: string
  timestamp: Date
  source: 'prometheus' | 'model_detect' | 'lstm_eta' | 'rag_engine' | 'orchestrator'
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
}

export default function BackendTraceVisualizer({ alerts, faultStatus }: { alerts: any[], faultStatus: any }) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const addLog = (source: LogEntry['source'], message: string, type: LogEntry['type']) => {
    setLogs(prev => [...prev, { id: Math.random().toString(36).substring(7), timestamp: new Date(), source, message, type }].slice(-50))
  }

  // Orchestrator actions
  useEffect(() => {
    if (faultStatus && faultStatus.active) {
       addLog('orchestrator', `POST /api/v1/faults/start -> Injected ${faultStatus.active}`, 'warning')
       setTimeout(() => {
         addLog('prometheus', `GET /api/v1/query?query=rate(ifHCInOctets[1m]) -> Spike Detected`, 'info')
       }, 800)
    }
  }, [faultStatus?.active])

  // AI Pipeline inferences
  useEffect(() => {
    if (alerts && alerts.length > 0) {
      const a = alerts[0]
      if (a.payload?.model_detection) {
        addLog('model_detect', `POST /predict (XGBoost) -> [Severity: ${a.class}]`, 'success')
      }
      if (a.payload?.q1_eta) {
        addLog('lstm_eta', `GET /inference/lstm -> ETA: ${a.payload.q1_eta}`, 'success')
      }
      if (a.payload?.q3_nlp) {
        addLog('rag_engine', `POST /v1/chat/completions (Phi-3 RAG) -> Generated SOP Context`, 'info')
      }
    }
  }, [alerts])

  // Background polling
  useEffect(() => {
    const interval = setInterval(() => {
      if (Math.random() > 0.7) {
         addLog('prometheus', `GET /api/v1/query?query=node_hwmon_temp_celsius -> 200 OK`, 'info')
      }
    }, 4500)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const getSourceIcon = (source: string) => {
    switch (source) {
      case 'prometheus': return <Database size={12} className="text-blue-400" />
      case 'model_detect': return <Brain size={12} className="text-purple-400" />
      case 'lstm_eta': return <Activity size={12} className="text-emerald-400" />
      case 'rag_engine': return <Zap size={12} className="text-amber-400" />
      default: return <Terminal size={12} className="text-gray-400" />
    }
  }

  return (
    <div className="bg-[#0b0f19] border border-[var(--deca-line)] rounded-lg overflow-hidden flex flex-col h-[320px] shadow-2xl font-mono text-[11px]">
      <div className="bg-[var(--deca-panel-2)] border-b border-[var(--deca-line)] px-3 py-2 flex items-center gap-2">
        <Terminal size={14} className="text-[var(--deca-accent)]" />
        <span className="text-gray-200 font-semibold tracking-widest text-xs uppercase">Live Backend Trace</span>
        <div className="ml-auto flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500/80"></div>
          <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/80"></div>
          <div className="w-2.5 h-2.5 rounded-full bg-green-500/80"></div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {logs.map(log => (
          <div key={log.id} className="flex items-start gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <span className="text-[var(--deca-mute)] shrink-0">[{log.timestamp.toISOString().split('T')[1].slice(0, -1)}]</span>
            <span className="shrink-0 mt-0.5">{getSourceIcon(log.source)}</span>
            <span className={`break-all ${log.type === 'error' ? 'text-red-400' : log.type === 'warning' ? 'text-amber-400' : log.type === 'success' ? 'text-green-400' : 'text-gray-300'}`}>
              <span className="text-[var(--deca-mute)] mr-2">[{log.source.toUpperCase()}]</span>
              {log.message}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
