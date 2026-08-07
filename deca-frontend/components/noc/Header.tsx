'use client'

import { AlertCircle, CheckCircle2, Beaker } from 'lucide-react'
import type { StationSnapshot } from '@/lib/telemetry-context'

interface HeaderProps {
  onOpenMethodology: () => void
  isAnomalyMode: boolean
  anomalyScore: number
  timeToImpactMinutes: number | null
  lastUpdated: string | null
  source: string
  prometheusReachable: boolean
  stations: StationSnapshot[]
  runId: string | null
  availableRuns: Array<{ run_id: string; mode: string; has_declarations: boolean }>
  onSelectRun: (id: string) => void
  actionableCount: number
  activePath: string | null
  conflict: boolean
}

export default function Header({
  onOpenMethodology,
  isAnomalyMode,
  anomalyScore,
  timeToImpactMinutes,
  lastUpdated,
  source,
  prometheusReachable,
  stations,
  runId,
  availableRuns,
  onSelectRun,
  actionableCount,
  activePath,
  conflict,
}: HeaderProps) {
  const onlineCount = stations.filter((s) => s.status === 'online').length

  return (
    <header className="deca-hero">
      <div className="deca-hero-veil" aria-hidden />
      <div className="relative z-10 grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-end">
        <div>
          <p className="deca-eyebrow">ISRO mission network · predictive SD-WAN demo</p>
          <h1 className="deca-brand">DECA</h1>
          <p className="deca-tagline mb-4">
            Inject a network problem → the model predicts the outage → Copilot explains it →
            you Approve a backup path (or wait and it heals itself).
          </p>
          <button
            onClick={onOpenMethodology}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-[var(--deca-primary)] bg-[var(--deca-primary)]/10 hover:bg-[var(--deca-primary)]/20 border border-[var(--deca-primary)]/30 rounded-md transition-colors"
          >
            <Beaker className="w-3.5 h-3.5" />
            Technical methodology (optional)
          </button>
        </div>

        <div className="deca-hero-controls">
          <label className="block">
            <span className="deca-field-label">Active run</span>
            <select
              className="deca-input mt-1 w-full"
              value={runId || ''}
              onChange={(e) => e.target.value && onSelectRun(e.target.value)}
            >
              <option value="">Select a live or replay run…</option>
              {availableRuns.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id}
                  {r.has_declarations ? '' : ' · no declarations'}
                </option>
              ))}
            </select>
          </label>

          <div className="deca-status-row">
            <div
              className={`deca-status-pill ${prometheusReachable ? 'is-ok' : 'is-warn'}`}
              title="Prometheus / fleet reachability"
            >
              {prometheusReachable ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                <AlertCircle className="w-4 h-4" />
              )}
              <span>{prometheusReachable ? 'Telemetry live' : 'Telemetry soft-offline'}</span>
            </div>
            <div className="deca-status-meta">
              <span>
                Traffic path <strong>{activePath === 'eth0' ? 'backup (eth0)' : activePath === 'gre' ? 'primary (GRE)' : activePath || '—'}</strong>
                {conflict ? ' · policy conflict' : ''}
              </span>
              <span>
                {actionableCount} decision{actionableCount === 1 ? '' : 's'} waiting
              </span>
              <span>
                {stations.length > 0
                  ? `${onlineCount}/${stations.length} stations`
                  : 'no station scrape yet'}
              </span>
            </div>
          </div>

          <p className="deca-hero-fine">
            {source || 'orchestrator'}
            {prometheusReachable ? '' : ' · Prom soft-offline'}
            {stations.length > 0 ? ` · ${onlineCount}/${stations.length} stations` : ''}
            {lastUpdated ? ` · ${lastUpdated}` : ''}
          </p>
        </div>
      </div>
    </header>
  )
}
