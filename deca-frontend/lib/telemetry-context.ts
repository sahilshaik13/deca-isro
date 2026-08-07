export interface MetricsSnapshot {
  network_throughput_in: number
  network_throughput_out: number
  link_jitter: number
  packet_loss: number
  routing_updates: number
  cpu_usage: number
  memory_usage: number
  latency_gre_ms?: number
  latency_eth0_ms?: number
  timestamp: string
}

export interface StationSnapshot {
  id: string
  host: string
  status: 'online' | 'offline'
  metrics: Record<string, number>
}

export interface CopilotData {
  root_cause: string
  runbook_steps: string[]
  mitigation_checklist: string[]
}

export interface DashboardResponse {
  success: boolean
  source: string
  prometheus_reachable: boolean
  stations: StationSnapshot[]
  metrics: MetricsSnapshot
  history: MetricsSnapshot[]
  prediction: {
    predicted_issue: string
    confidence_score: number
    time_to_impact_minutes: number | null
    contributing_signals: Record<string, number>
  }
  data: {
    prediction: string
    anomaly_score: number
    confidence_score: number
    time_to_impact_minutes: number | null
    contributing_signals: Record<string, number>
    metrics_summary: MetricsSnapshot
  }
  copilot: CopilotData
  last_updated: string
}

export interface TelemetryState {
  current: MetricsSnapshot | null
  history: MetricsSnapshot[]
  stations: StationSnapshot[]
  source: string
  prometheusReachable: boolean
  isAnomaly: boolean
  anomalyScore: number
  prediction: string
  timeToImpactMinutes: number | null
  copilotResponse: CopilotData
  loading: boolean
  error: string | null
  lastUpdated: string | null
}

export const defaultTelemetryState: TelemetryState = {
  current: null,
  history: [],
  stations: [],
  source: '',
  prometheusReachable: false,
  isAnomaly: false,
  anomalyScore: 0,
  prediction: '',
  timeToImpactMinutes: null,
  copilotResponse: {
    root_cause: '',
    runbook_steps: [],
    mitigation_checklist: [],
  },
  loading: true,
  error: null,
  lastUpdated: null,
}
