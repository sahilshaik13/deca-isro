'use client'

import Header from '@/components/noc/Header'
import TopologyMap from '@/components/noc/TopologyMap'
import MissionClasses from '@/components/noc/MissionClasses'
import AlertRail from '@/components/noc/AlertRail'
import TelemetryGrid from '@/components/noc/TelemetryGrid'
import FleetStrip from '@/components/noc/FleetStrip'
import SimulationControl from '@/components/noc/SimulationControl'
import FabricSelect from '@/components/noc/FabricSelect'
import FaultButtons from '@/components/noc/FaultButtons'
import TrafficButtons from '@/components/noc/TrafficButtons'
import TerminalDrawer from '@/components/noc/TerminalDrawer'
import { useTelemetry } from '@/hooks/useTelemetry'
import { useOrchestrator } from '@/hooks/useOrchestrator'

export default function Page() {
  const telemetry = useTelemetry()
  const orch = useOrchestrator()
  const activeFabric = orch.fabricStatus?.active || orch.fleet?.fabric || 'pi'
  const topoLayout =
    orch.fleet?.topology || orch.fabricStatus?.topology || null
  const actionableCount = orch.alerts.filter(
    (a) =>
      a.status === 'active' &&
      a.class &&
      !['healthy', 'advisory_clear', 'confirmed_clear'].includes(a.class),
  ).length
  const hasRaise = orch.alerts.some((a) => a.event === 'confirmed_raise')

  return (
    <main className="deca-shell">
      <Header
        isAnomalyMode={telemetry.isAnomaly || hasRaise}
        anomalyScore={telemetry.anomalyScore}
        timeToImpactMinutes={telemetry.timeToImpactMinutes}
        lastUpdated={telemetry.lastUpdated}
        source={telemetry.source || 'orchestrator'}
        prometheusReachable={telemetry.prometheusReachable}
        stations={telemetry.stations}
        runId={orch.runId}
        availableRuns={orch.availableRuns}
        onSelectRun={(id) => void orch.selectRun(id)}
        actionableCount={actionableCount}
        activePath={orch.fleet?.mission?.active_path ?? null}
        conflict={Boolean(orch.fleet?.mission?.conflict)}
      />

      <FleetStrip sites={orch.fleet?.sites || []} />

      <div className="deca-main">
        <section className="deca-main-left space-y-6">
          <FabricSelect
            status={orch.fabricStatus}
            busy={orch.fabricBusy || orch.faultBusy || orch.trafficBusy}
            onSelect={(id) => void orch.onFabricSelect(id)}
          />
          <TrafficButtons
            status={orch.trafficStatus}
            busy={orch.trafficBusy}
            fabric={activeFabric}
            onStart={(profile) => void orch.onTrafficStart(profile)}
            onStop={() => void orch.onTrafficStop()}
          />
          <FaultButtons
            status={orch.faultStatus}
            busy={orch.faultBusy}
            fabric={activeFabric}
            onStart={(id) => void orch.onFaultStart(id)}
            onClear={() => void orch.onFaultClear()}
          />
          <SimulationControl
            status={orch.simulation}
            busy={orch.simBusy}
            onStart={(dry) => void orch.onSimStart(dry)}
            onStop={() => void orch.onSimStop()}
          />
          <TopologyMap
            fabric={activeFabric}
            layout={topoLayout}
            sites={orch.fleet?.sites || []}
            mission={orch.fleet?.mission || null}
            alerts={orch.alerts}
            onCaptureLink={(link) => void orch.onCaptureLink(link)}
            captureBusy={orch.captureBusy}
            captureMessage={orch.captureMessage}
            recentAction={
              orch.history?.actions?.[0]
                ? {
                    action: orch.history.actions[0].action,
                    alert_id: orch.history.actions[0].alert_id,
                    ts: orch.history.actions[0].ts,
                  }
                : null
            }
          />
          <MissionClasses mission={orch.fleet?.mission || null} />
          <TelemetryGrid
            current={telemetry.current}
            history={telemetry.history}
            loading={telemetry.loading}
            error={telemetry.error}
          />
        </section>

        <aside className="deca-main-right space-y-6">
          <AlertRail
            alerts={orch.alerts}
            actionBusy={orch.actionBusy}
            onApprove={(id, path) => void orch.onApprove(id, path)}
            onReject={(id) => void orch.onReject(id)}
            activePath={orch.fleet?.mission?.active_path ?? null}
            mission={orch.fleet?.mission || null}
            sites={orch.fleet?.sites || []}
          />
        </aside>
      </div>

      {orch.error ? (
        <p className="mt-4 text-xs font-mono text-[var(--deca-warn)]">{orch.error}</p>
      ) : null}

      <div className="deca-term-spacer" aria-hidden />
      <TerminalDrawer />
    </main>
  )
}
