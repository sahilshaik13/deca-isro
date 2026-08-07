import { useEffect, useRef, useState } from 'react'
import { useDecaState } from '@/hooks/useDecaState'
import {
  defaultTelemetryState,
  MetricsSnapshot,
  TelemetryState,
} from '@/lib/telemetry-context'

const HISTORY_CAP = 60

function isMetrics(m: unknown): m is MetricsSnapshot {
  if (!m || typeof m !== 'object') return false
  const row = m as Record<string, unknown>
  return (
    typeof row.network_throughput_in === 'number' &&
    typeof row.link_jitter === 'number' &&
    typeof row.packet_loss === 'number'
  )
}

export function useTelemetry(): TelemetryState & {
  decaState: ReturnType<typeof useDecaState>['decaState']
  refetch: () => Promise<void>
} {
  const { decaState, loading, error, refetch } = useDecaState()
  const [state, setState] = useState<TelemetryState>(defaultTelemetryState)
  const localHistory = useRef<MetricsSnapshot[]>([])

  useEffect(() => {
    if (loading && !decaState) {
      setState((prev) => ({ ...prev, loading: true }))
      return
    }

    if (!decaState) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error: error ?? 'Failed to fetch telemetry from DECA backend',
      }))
      return
    }

    const prediction =
      decaState.prediction?.predicted_issue || decaState.data?.prediction || 'normal'
    const confidence =
      decaState.data?.confidence_score ?? decaState.prediction?.confidence_score ?? 0
    const isAnomalous = prediction === 'anomaly_detected'

    const metrics = isMetrics(decaState.metrics) ? decaState.metrics : null
    const fromApi = Array.isArray(decaState.history)
      ? decaState.history.filter(isMetrics)
      : []

    let history = fromApi
    if (metrics) {
      const last = localHistory.current[localHistory.current.length - 1]
      const changed =
        !last ||
        last.timestamp !== metrics.timestamp ||
        last.network_throughput_in !== metrics.network_throughput_in ||
        last.link_jitter !== metrics.link_jitter ||
        last.packet_loss !== metrics.packet_loss
      if (changed) {
        localHistory.current = [...localHistory.current, metrics].slice(-HISTORY_CAP)
      }
      // Prefer longer of API ring vs client ring so charts always grow.
      if (localHistory.current.length > history.length) {
        history = localHistory.current
      } else if (history.length === 0) {
        history = [metrics]
      }
    }

    setState({
      current: metrics,
      history,
      stations: decaState.stations || [],
      source: decaState.source || 'unknown',
      prometheusReachable: Boolean(decaState.prometheus_reachable),
      isAnomaly: isAnomalous,
      anomalyScore: confidence,
      prediction,
      timeToImpactMinutes:
        decaState.data?.time_to_impact_minutes ??
        decaState.prediction?.time_to_impact_minutes ??
        null,
      copilotResponse: decaState.copilot || defaultTelemetryState.copilotResponse,
      loading: false,
      error: null,
      lastUpdated:
        decaState.last_updated || metrics?.timestamp || new Date().toISOString(),
    })
  }, [decaState, loading, error])

  return { ...state, decaState, refetch }
}
