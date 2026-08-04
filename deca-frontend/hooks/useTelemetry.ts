import { useEffect, useState } from 'react'
import { useDecaState } from '@/hooks/useDecaState'
import { defaultTelemetryState, TelemetryState } from '@/lib/telemetry-context'

export function useTelemetry(): TelemetryState & {
  decaState: ReturnType<typeof useDecaState>['decaState']
  refetch: () => Promise<void>
} {
  const { decaState, loading, error, refetch } = useDecaState()
  const [state, setState] = useState<TelemetryState>(defaultTelemetryState)

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

    setState({
      current: decaState.metrics,
      history: decaState.history?.length ? decaState.history : [decaState.metrics],
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
        decaState.last_updated || decaState.metrics?.timestamp || new Date().toISOString(),
    })
  }, [decaState, loading, error])

  return { ...state, decaState, refetch }
}
