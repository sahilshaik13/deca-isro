'use client'

import { useState } from 'react'
import { Check, AlertTriangle, Radio } from 'lucide-react'

interface CopilotTerminalProps {
  isAnomaly: boolean
  copilotResponse: {
    root_cause: string
    runbook_steps: string[]
    mitigation_checklist: string[]
  }
  loading: boolean
  source: string
}

export default function CopilotTerminal({
  isAnomaly,
  copilotResponse,
  loading,
  source,
}: CopilotTerminalProps) {
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({})

  const toggleCheck = (index: number) => {
    setCheckedItems((prev) => ({ ...prev, [index]: !prev[index] }))
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-slate-100 font-mono">AI Copilot Terminal</h2>
        <div className="bg-slate-950/60 border-2 border-emerald-500/20 rounded-lg p-6 min-h-96 animate-pulse">
          <div className="h-6 bg-slate-800 rounded mb-4 w-1/2" />
          <div className="h-12 bg-slate-800 rounded mb-4" />
          <div className="h-8 bg-slate-800 rounded" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold text-slate-100 font-mono">AI Copilot Terminal</h2>

      <div
        className={`rounded-lg border-2 p-6 space-y-6 min-h-96 ${
          isAnomaly ? 'bg-slate-950/60 border-rose-500/30' : 'bg-slate-950/60 border-emerald-500/20'
        }`}
      >
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${isAnomaly ? 'bg-rose-500 animate-pulse' : 'bg-emerald-500'}`} />
          <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
          <div className="w-3 h-3 rounded-full bg-slate-700" />
          <span className="text-xs font-mono text-slate-400 ml-4">
            DECA_COPILOT • {isAnomaly ? 'ANOMALY_MODE' : 'MONITOR_MODE'} • {source}
          </span>
        </div>

        {!isAnomaly ? (
          <div className="space-y-4 py-4">
            <div className="flex items-start gap-3 text-slate-300">
              <Radio className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
              <p className="font-mono text-sm leading-relaxed">{copilotResponse.root_cause}</p>
            </div>
            <p className="text-slate-500 font-mono text-xs">All charts and confidence scores are from the live backend.</p>
          </div>
        ) : (
          <>
            <div className="bg-rose-950/40 border border-rose-500/50 rounded p-3">
              <p className="text-rose-300 font-mono text-sm font-semibold flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                Anomaly detected by ML ensemble
              </p>
            </div>

            {copilotResponse.root_cause && (
              <div className="space-y-2">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">Root Cause Analysis</h3>
                <p className="text-slate-300 font-mono text-sm leading-relaxed">{copilotResponse.root_cause}</p>
              </div>
            )}

            {copilotResponse.runbook_steps.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">Diagnostic Runbook</h3>
                <ol className="space-y-1">
                  {copilotResponse.runbook_steps.map((step, idx) => (
                    <li key={idx} className="text-slate-300 font-mono text-xs leading-relaxed">
                      <span className="text-slate-500">{idx + 1}.</span> {step}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {copilotResponse.mitigation_checklist.length > 0 && (
              <div className="space-y-2 pt-4 border-t border-slate-700">
                <h3 className="text-emerald-400 font-mono text-sm font-semibold">Operator Actions</h3>
                <div className="space-y-2">
                  {copilotResponse.mitigation_checklist.map((item, idx) => (
                    <button
                      key={idx}
                      onClick={() => toggleCheck(idx)}
                      className={`flex items-center gap-2 w-full text-left p-2 rounded transition-colors ${
                        checkedItems[idx]
                          ? 'bg-emerald-950/40 border border-emerald-500/30'
                          : 'bg-slate-900/40 border border-slate-700/50 hover:border-slate-600/50'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center text-xs transition-colors ${
                          checkedItems[idx] ? 'bg-emerald-500 border-emerald-500' : 'border-slate-600 bg-transparent'
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
            )}
          </>
        )}

        <div className="pt-4 border-t border-slate-700">
          <p className="text-slate-500 font-mono text-xs">
            $ <span className="animate-pulse">streaming from backend...</span>
          </p>
        </div>
      </div>
    </div>
  )
}
