import { getApiBaseUrl } from '@/lib/env'
import type { DashboardResponse } from '@/lib/telemetry-context'

export interface PredictRequest {
  run_id: string
  metrics: Record<string, unknown>[]
}

export interface PredictResponse {
  success: boolean
  data: {
    predicted_issue: string
    confidence_score: number
    time_to_impact_minutes: number | null
    contributing_signals: Record<string, number>
  }
  copilot: DashboardResponse['copilot']
}

export type FabricId = 'pi' | 'gns3'

export interface FleetSite {
  id: string
  name: string
  role: string
  hosts: string[]
  mission_class: string
  status: string
  hosts_state: Array<{
    host: string
    confirmed?: string | null
    advisory?: string | null
    confidence?: number | null
    eta_minutes?: number | null
    metrics?: {
      latency_gre_ms?: number
      latency_eth0_ms?: number
      jitter_ms?: number
      packet_loss_pct?: number
      throughput_mbps?: number
      [key: string]: unknown
    } | null
  }>
  virtual?: boolean
  netns?: string
}

export interface MissionState {
  ok: boolean
  active_path?: string
  ttc_wanted?: string
  payload_wanted?: string
  conflict?: number
  human_override?: string | null
  last_reason?: string | null
  path_latency_ms?: { gre?: number | null; eth0?: number | null }
  thresholds?: Record<string, unknown>
  error?: string
}

export interface FleetResponse {
  run_id: string | null
  fabric?: FabricId
  prometheus?: string
  topology?: TopologyLayout
  sites: FleetSite[]
  ticks: unknown[]
  mission: MissionState
}

export interface TopologyNode {
  id: string
  kind?: string
  label: string
  sub?: string
  lo?: string
  x: number
  y: number
  w: number
  h: number
  fleet_id?: string
  muted?: boolean
}

export interface TopologyLink {
  id: string
  kind?: string
  from: string
  to: string
  label?: string
  curve?: string
}

export interface TopologyFrame {
  x: number
  y: number
  w: number
  h: number
  label: string
  core?: boolean
}

export interface TopologyLayout {
  fabric?: string
  label?: string
  subtitle?: string
  viewBox?: number[]
  nodes?: TopologyNode[]
  links?: TopologyLink[]
  frames?: TopologyFrame[]
}

export interface AlertRow {
  id: number
  run_id: string
  ts: string
  host: string | null
  class: string | null
  event: string | null
  confidence: number | null
  eta: number | null
  status: string
  payload?: Record<string, unknown>
}

async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/${path}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) {
      // 404 = missing route; 500/502/503 = backend blip (disk full, restart) — retry on poll
      const soft =
        response.status === 404 ||
        response.status === 500 ||
        response.status === 502 ||
        response.status === 503
      if (!soft) {
        console.error(`DECA GET ${path} failed:`, response.status)
      } else if (process.env.NODE_ENV === 'development' && response.status !== 404) {
        console.warn(`DECA GET ${path} soft ${response.status} (retry on next poll)`)
      }
      return null
    }
    return (await response.json()) as T
  } catch (error) {
    // NetworkError while HMR/backend restarts — transient
    if (process.env.NODE_ENV === 'development') {
      console.warn(`DECA GET ${path} unreachable (retry on next poll)`)
    } else {
      console.error(`DECA GET ${path} failed:`, error)
    }
    return null
  }
}

async function apiPost<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    })
    if (!response.ok) {
      const text = await response.text().catch(() => '')
      console.error(`DECA POST ${path} failed:`, response.status, text.slice(0, 200))
      return null
    }
    return (await response.json()) as T
  } catch (error) {
    console.error(`DECA POST ${path} failed:`, error)
    return null
  }
}

export async function fetchDashboard(): Promise<DashboardResponse | null> {
  const url = `${getApiBaseUrl()}/dashboard`
  const maxAttempts = 3
  let lastDetail = ''

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      })

      if (response.ok) {
        return await response.json()
      }

      const retryable = response.status === 500 || response.status === 502 || response.status === 503
      lastDetail = await response.text().catch(() => '')

      if (!retryable || attempt === maxAttempts) {
        if (attempt === maxAttempts) {
          console.warn(
            `DECA dashboard unavailable after ${maxAttempts} attempts: ${response.status}`,
            lastDetail.slice(0, 160),
          )
        }
        return null
      }

      await new Promise((resolve) => setTimeout(resolve, 400 * attempt))
    } catch (error) {
      lastDetail = error instanceof Error ? error.message : String(error)
      if (attempt === maxAttempts) {
        console.warn('DECA dashboard fetch failed:', lastDetail)
        return null
      }
      await new Promise((resolve) => setTimeout(resolve, 400 * attempt))
    }
  }

  return null
}

export async function fetchPredict(payload: PredictRequest): Promise<PredictResponse | null> {
  return apiPost<PredictResponse>('predict', payload)
}

export async function fetchFleet(runId?: string | null): Promise<FleetResponse | null> {
  const q = runId ? `fleet?run_id=${encodeURIComponent(runId)}` : 'fleet'
  return apiGet<FleetResponse>(q)
}

export async function fetchAlerts(runId?: string | null) {
  const q = runId ? `alerts?run_id=${encodeURIComponent(runId)}` : 'alerts'
  return apiGet<{ run_id: string | null; active: AlertRow[]; history: AlertRow[] }>(q)
}

export async function fetchRuns() {
  return apiGet<{
    active_run_id: string | null
    runs: Array<{ run_id: string; mode: string; started_at: string; notes: string }>
    available: Array<{ run_id: string; mode: string; path: string; has_declarations: boolean }>
  }>('runs')
}

export async function bindRun(runId: string, mode = 'replay', notes = '') {
  return apiPost<{ ok: boolean }>('runs', { run_id: runId, mode, notes })
}

export async function askQuestion(question: string, runId?: string | null) {
  return apiPost<{
    ok: boolean
    answer: string
    generation_path: string
    intent?: Record<string, unknown>
  }>('ask', { question, run_id: runId || undefined })
}

export async function approveAlert(
  alertId: number,
  opts: { path?: string; reason?: string; operator_note?: string } = {},
) {
  return apiPost<{ ok: boolean; controller?: Record<string, unknown>; proposal?: unknown }>(
    `actions/${alertId}/approve`,
    {
      path: opts.path,
      reason: opts.reason || 'orchestrator_approve',
      operator_note: opts.operator_note || '',
      approved_by: 'deca-ui',
    },
  )
}

export async function rejectAlert(alertId: number, operatorNote = '') {
  return apiPost<{ ok: boolean }>(`actions/${alertId}/reject`, {
    operator_note: operatorNote,
    approved_by: 'deca-ui',
  })
}

export async function fetchHistory(runId?: string | null) {
  const q = runId ? `history?run_id=${encodeURIComponent(runId)}` : 'history'
  return apiGet<{
    run_id: string | null
    alerts: AlertRow[]
    queries: Array<{ id: number; ts: string; question: string; answer: string; generation_path: string }>
    actions: Array<{
      id: number
      ts: string
      alert_id: number | null
      action: string
      proposal?: unknown
      result?: unknown
      operator_note: string
    }>
  }>(q)
}

export interface SimulationStatus {
  running?: boolean
  finished?: boolean
  ok?: boolean
  phase?: number | null
  phase_name?: string | null
  message?: string
  ui_expectation?: string
  waiting_for_approve?: boolean
  elapsed_s?: number
  dry?: boolean
  log_tail?: string[]
  pid?: number
}

export async function fetchSimulationStatus() {
  return apiGet<SimulationStatus>('simulation/status')
}

export async function startSimulation(dry = false) {
  return apiPost<{
    ok: boolean
    pid?: number
    dry?: boolean
    fabric?: string
    run_id?: string
    active_run_id?: string
    cleared?: Record<string, number>
    status?: SimulationStatus
    error?: string
  }>('simulation/start', { dry, started_by: 'deca-ui' })
}

export async function stopSimulation(reason = 'operator_stop') {
  return apiPost<{ ok: boolean; status?: SimulationStatus }>('simulation/stop', { reason })
}

export interface FaultInfo {
  id: string
  label: string
  blurb: string
  duration_hint_s?: number
}

export interface FaultDemoStatus {
  running?: boolean
  fault_id?: string | null
  label?: string
  message?: string
  seeded_alert?: number | null
  log_tail?: string[]
  catalog?: FaultInfo[]
}

export async function fetchFaultStatus() {
  return apiGet<FaultDemoStatus>('faults/status')
}

export async function startFault(faultId: string) {
  return apiPost<{ ok: boolean; fault_id?: string; status?: FaultDemoStatus; error?: string }>(
    'faults/start',
    { fault_id: faultId, started_by: 'deca-ui' },
  )
}

export async function clearFault(reason = 'operator_clear') {
  return apiPost<{ ok: boolean; status?: FaultDemoStatus }>('faults/clear', { reason })
}

export interface FabricInfo {
  id: FabricId
  label: string
  blurb: string
  ready?: boolean
  sla_label?: string
}

export interface FabricSlaClass {
  latency_ms?: number
  jitter_ms?: number
  loss_pct?: number
  tos?: string
  vrf?: string
  primary?: string
  backup?: string | null
}

export interface FabricStatus {
  active?: FabricId
  fabrics?: FabricInfo[]
  topology?: TopologyLayout
  sla?: {
    fabric?: FabricId
    label?: string
    classes?: Record<string, FabricSlaClass>
    ce_tiers?: Record<
      string,
      { site?: string; tier?: string; availability?: number }
    >
    chaos?: string[]
  }
  flow?: { summary?: string; controller?: string }
  prometheus?: {
    active?: string
    pi?: string
    gns3?: string
    gns3_exporter_ok?: boolean | null
  }
  storage?: {
    gns3_root?: string
    gns3_mounted?: boolean
  }
}

export async function fetchFabric() {
  return apiGet<FabricStatus>('fabric')
}

export async function setFabric(active: FabricId, setBy = 'deca-ui') {
  return apiPost<FabricStatus & { ok?: boolean; error?: string }>('fabric', {
    active,
    set_by: setBy,
  })
}

export interface TrafficStatus {
  running?: boolean
  fabric?: string
  profile?: string | null
  duration_s?: number
  message?: string
  log_tail?: string[]
  profiles?: string[]
}

export async function fetchTrafficStatus() {
  return apiGet<TrafficStatus>('traffic')
}

export async function startTraffic(profile: string, durationS = 0) {
  return apiPost<{ ok: boolean; status?: TrafficStatus; error?: string }>(
    'traffic/start',
    { profile, duration_s: durationS, started_by: 'deca-ui' },
  )
}

export async function stopTraffic(reason = 'operator_stop') {
  return apiPost<{ ok: boolean; status?: TrafficStatus }>('traffic/stop', {
    reason,
  })
}

export interface CaptureStatus {
  active?: Array<Record<string, unknown>>
  last?: Record<string, unknown> | null
  message?: string
  fabric?: string
  capture_root?: string
  wireshark?: string | null
}

export async function fetchCaptureStatus() {
  return apiGet<CaptureStatus>('capture')
}

export async function openLinkCapture(opts: {
  link_id: string
  from_id?: string
  to_id?: string
  fabric?: string
}) {
  return apiPost<{
    ok: boolean
    pcap?: string
    message?: string
    error?: string
    ends?: string[]
  }>('capture/open', opts)
}

export async function stopLinkCapture(linkId?: string) {
  return apiPost<{ ok: boolean }>('capture/stop', { link_id: linkId ?? null })
}

export type TerminalTarget = 'brain' | 'station1' | 'station2' | 'station3'

export interface TerminalSessionMeta {
  id: string
  label: string
  target: string
  mode: 'monitor' | 'interactive' | string
  readonly: boolean
  status: string
  cmd_summary?: string
  created_at?: number
}

async function apiDelete<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/${path}`, {
      method: 'DELETE',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) {
      const text = await response.text().catch(() => '')
      console.error(`DECA DELETE ${path} failed:`, response.status, text.slice(0, 200))
      return null
    }
    return (await response.json()) as T
  } catch (error) {
    console.error(`DECA DELETE ${path} failed:`, error)
    return null
  }
}

export async function listTerminals() {
  return apiGet<{ terminals: TerminalSessionMeta[] }>('terminals')
}

export async function createTerminal(target: TerminalTarget) {
  return apiPost<{ ok: boolean; terminal: TerminalSessionMeta; detail?: string }>('terminals', {
    target,
  })
}

export async function deleteTerminal(sessionId: string) {
  return apiDelete<{ ok: boolean }>(`terminals/${encodeURIComponent(sessionId)}`)
}
