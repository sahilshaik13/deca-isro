'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  approveAlert,
  askQuestion,
  bindRun,
  clearFault,
  fetchAlerts,
  fetchFabric,
  fetchFaultStatus,
  fetchFleet,
  fetchHistory,
  fetchRuns,
  fetchSimulationStatus,
  fetchTrafficStatus,
  rejectAlert,
  setFabric,
  startFault,
  startSimulation,
  startTraffic,
  stopSimulation,
  stopTraffic,
  openLinkCapture,
  type AlertRow,
  type FabricId,
  type FabricStatus,
  type FaultDemoStatus,
  type FleetResponse,
  type SimulationStatus,
  type TrafficStatus,
} from '@/lib/api'
import { getPollIntervalMs } from '@/lib/env'

export function useOrchestrator() {
  const [runId, setRunId] = useState<string | null>(null)
  const [availableRuns, setAvailableRuns] = useState<
    Array<{ run_id: string; mode: string; has_declarations: boolean }>
  >([])
  const [fleet, setFleet] = useState<FleetResponse | null>(null)
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [history, setHistory] = useState<Awaited<ReturnType<typeof fetchHistory>>>(null)
  const [askBusy, setAskBusy] = useState(false)
  const [askLog, setAskLog] = useState<Array<{ q: string; a: string; path: string }>>([])
  const [actionBusy, setActionBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [simulation, setSimulation] = useState<SimulationStatus | null>(null)
  const [simBusy, setSimBusy] = useState(false)
  const [faultStatus, setFaultStatus] = useState<FaultDemoStatus | null>(null)
  const [faultBusy, setFaultBusy] = useState(false)
  const [fabricStatus, setFabricStatus] = useState<FabricStatus | null>(null)
  const [fabricBusy, setFabricBusy] = useState(false)
  const [trafficStatus, setTrafficStatus] = useState<TrafficStatus | null>(null)
  const [trafficBusy, setTrafficBusy] = useState(false)
  const [captureBusy, setCaptureBusy] = useState(false)
  const [captureMessage, setCaptureMessage] = useState<string | null>(null)

  const refresh = useCallback(async (forcedRunId?: string | null) => {
    const rid = forcedRunId !== undefined ? forcedRunId : runId
    try {
      const [runs, fleetData, alertData, hist, sim, fault, fab, traffic] =
        await Promise.all([
          fetchRuns(),
          fetchFleet(rid),
          fetchAlerts(rid),
          fetchHistory(rid),
          fetchSimulationStatus(),
          fetchFaultStatus(),
          fetchFabric(),
          fetchTrafficStatus(),
        ])
      if (runs) {
        setAvailableRuns(runs.available || [])
        if (!rid && runs.active_run_id) {
          setRunId(runs.active_run_id)
        }
      }
      if (fleetData) setFleet(fleetData)
      if (alertData) setAlerts(alertData.active || [])
      if (hist) setHistory(hist)
      if (sim) setSimulation(sim)
      if (fault) setFaultStatus(fault)
      if (fab) setFabricStatus(fab)
      if (traffic) setTrafficStatus(traffic)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'orchestrator refresh failed')
    }
  }, [runId])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, getPollIntervalMs())
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [refresh])

  const selectRun = useCallback(async (id: string, mode = 'replay') => {
    await bindRun(id, mode)
    setRunId(id)
  }, [])

  const ask = useCallback(
    async (question: string) => {
      setAskBusy(true)
      try {
        const res = await askQuestion(question, runId)
        if (res?.answer) {
          setAskLog((prev) =>
            [{ q: question, a: res.answer, path: res.generation_path || '' }, ...prev].slice(0, 20),
          )
        }
        await refresh()
        return res
      } finally {
        setAskBusy(false)
      }
    },
    [runId, refresh],
  )

  const onApprove = useCallback(
    async (alertId: number, path?: string) => {
      setActionBusy(alertId)
      try {
        const res = await approveAlert(alertId, { path })
        // Backend also clears inject on steer; belt-and-suspenders for UI state.
        try {
          await clearFault('steered')
        } catch {
          /* ignore */
        }
        await refresh()
        return res
      } finally {
        setActionBusy(null)
      }
    },
    [refresh],
  )

  const onReject = useCallback(
    async (alertId: number) => {
      setActionBusy(alertId)
      try {
        const res = await rejectAlert(alertId)
        await refresh()
        return res
      } finally {
        setActionBusy(null)
      }
    },
    [refresh],
  )

  const onSimStart = useCallback(
    async (dry: boolean) => {
      setSimBusy(true)
      setError(null)
      // Optimistic clear so previous Decide/history don't linger until poll
      setAlerts([])
      setHistory(null)
      setAskLog([])
      try {
        const res = await startSimulation(dry)
        if (res?.status) setSimulation(res.status)
        const fab =
          (res as { fabric?: string } | null)?.fabric ||
          fabricStatus?.active ||
          'gns3'
        const bound =
          (res as { active_run_id?: string; run_id?: string } | null)
            ?.active_run_id ||
          (res as { run_id?: string } | null)?.run_id ||
          (fab === 'gns3' ? 'sim-gns3' : 'sim-live')
        setRunId(bound)
        try {
          await bindRun(bound, 'live', `timeline start (${fab})`)
        } catch {
          /* bind best-effort */
        }
        await refresh(bound)
        return res
      } finally {
        setSimBusy(false)
      }
    },
    [refresh, fabricStatus?.active],
  )

  const onSimStop = useCallback(async () => {
    setSimBusy(true)
    try {
      const res = await stopSimulation()
      if (res?.status) setSimulation(res.status)
      await refresh()
      return res
    } finally {
      setSimBusy(false)
    }
  }, [refresh])

  const onFaultStart = useCallback(
    async (faultId: string) => {
      setFaultBusy(true)
      try {
        const res = await startFault(faultId)
        if (res?.status) setFaultStatus(res.status)
        await refresh()
        return res
      } finally {
        setFaultBusy(false)
      }
    },
    [refresh],
  )

  const onFaultClear = useCallback(async () => {
    setFaultBusy(true)
    try {
      const res = await clearFault()
      if (res?.status) setFaultStatus(res.status)
      await refresh()
      return res
    } finally {
      setFaultBusy(false)
    }
  }, [refresh])

  const onFabricSelect = useCallback(
    async (fabric: FabricId) => {
      setFabricBusy(true)
      setCaptureMessage(null)
      setError(null)
      try {
        const res = await setFabric(fabric)
        if (res) setFabricStatus(res)
        // Rebind Decide run to fabric-scoped id returned by backend
        const bound =
          (res as { active_run_id?: string } | null)?.active_run_id ||
          (fabric === 'gns3' ? 'sim-gns3' : 'sim-live')
        setRunId(bound)
        try {
          await bindRun(bound, 'live', `fabric_switch to ${fabric}`)
        } catch {
          /* bind best-effort */
        }
        await refresh(bound)
        return res
      } finally {
        setFabricBusy(false)
      }
    },
    [refresh],
  )

  const onTrafficStart = useCallback(
    async (profile: string) => {
      setTrafficBusy(true)
      try {
        const res = await startTraffic(profile, 0)
        if (res?.status) setTrafficStatus(res.status)
        await refresh()
        return res
      } finally {
        setTrafficBusy(false)
      }
    },
    [refresh],
  )

  const onTrafficStop = useCallback(async () => {
    setTrafficBusy(true)
    try {
      const res = await stopTraffic()
      if (res?.status) setTrafficStatus(res.status)
      await refresh()
      return res
    } finally {
      setTrafficBusy(false)
    }
  }, [refresh])

  const onCaptureLink = useCallback(
    async (link: { link_id: string; from_id: string; to_id: string }) => {
      setCaptureBusy(true)
      setCaptureMessage(`opening ${link.link_id}…`)
      try {
        const fab = fabricStatus?.active || 'pi'
        const res = await openLinkCapture({
          link_id: link.link_id,
          from_id: link.from_id,
          to_id: link.to_id,
          fabric: fab,
        })
        if (res?.ok) {
          setCaptureMessage(res.message || `Wireshark ← ${res.pcap || link.link_id}`)
        } else {
          setCaptureMessage(res?.error || 'capture failed')
        }
        return res
      } finally {
        setCaptureBusy(false)
      }
    },
    [fabricStatus?.active],
  )

  return {
    runId,
    availableRuns,
    fleet,
    alerts,
    history,
    askBusy,
    askLog,
    actionBusy,
    error,
    simulation,
    simBusy,
    faultStatus,
    faultBusy,
    fabricStatus,
    fabricBusy,
    trafficStatus,
    trafficBusy,
    captureBusy,
    captureMessage,
    selectRun,
    ask,
    onApprove,
    onReject,
    onSimStart,
    onSimStop,
    onFaultStart,
    onFaultClear,
    onFabricSelect,
    onTrafficStart,
    onTrafficStop,
    onCaptureLink,
    refresh,
  }
}
