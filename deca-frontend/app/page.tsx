'use client'

import { useState } from 'react'
import Header from '@/components/noc/Header'
import TopologyMap from '@/components/noc/TopologyMap'
import MissionClasses from '@/components/noc/MissionClasses'
import AlertRail from '@/components/noc/AlertRail'
import TelemetryGrid from '@/components/noc/TelemetryGrid'
import FleetStrip from '@/components/noc/FleetStrip'
import LabControls from '@/components/noc/LabControls'
import TerminalDrawer from '@/components/noc/TerminalDrawer'
import MethodologyModal from '@/components/noc/MethodologyModal'
import BackendTraceVisualizer from '@/components/noc/BackendTraceVisualizer'
import CopilotTerminal from '@/components/noc/CopilotTerminal'
import FlowGuide from '@/components/noc/FlowGuide'
import { useTelemetry } from '@/hooks/useTelemetry'
import { useOrchestrator } from '@/hooks/useOrchestrator'

export default function Page() {
  const [isMethodologyOpen, setIsMethodologyOpen] = useState(false)
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
  const demoLive =
    Boolean(orch.faultStatus?.running) || Boolean(orch.simulation?.running)

  return (
    <main className={`deca-shell${demoLive ? ' is-demo-live' : ''}`}>
      <MethodologyModal isOpen={isMethodologyOpen} onClose={() => setIsMethodologyOpen(false)} />
      <Header
        onOpenMethodology={() => setIsMethodologyOpen(true)}
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
        conflict={Boolean(
          orch.fleet?.mission?.conflict &&
            orch.fleet?.mission?.ttc_wanted !== orch.fleet?.mission?.payload_wanted,
        )}
      />

      <FleetStrip sites={orch.fleet?.sites || []} />

      <FlowGuide
        actionableCount={actionableCount}
        faultRunning={Boolean(orch.faultStatus?.running)}
        hasCopilot={Boolean(
          (telemetry.isAnomaly || hasRaise) && telemetry.copilotResponse?.root_cause,
        )}
      />

      <div className="deca-main">
        <section className="deca-main-left space-y-5">
          <div className="deca-col-label">
            <span className="deca-ps13-tag">Watch</span>
            <span>Live network</span>
            <span className="deca-col-label-hint">sites · path · metrics</span>
          </div>

          <LabControls
            fabricStatus={orch.fabricStatus}
            fabricBusy={orch.fabricBusy}
            onFabricSelect={(id) => void orch.onFabricSelect(id)}
            trafficStatus={orch.trafficStatus}
            trafficBusy={orch.trafficBusy}
            activeFabric={activeFabric}
            onTrafficStart={(profile) => void orch.onTrafficStart(profile)}
            onTrafficStop={() => void orch.onTrafficStop()}
            faultStatus={orch.faultStatus}
            faultBusy={orch.faultBusy}
            onFaultStart={(id) => void orch.onFaultStart(id)}
            onFaultClear={() => void orch.onFaultClear()}
            simulation={orch.simulation}
            simBusy={orch.simBusy}
            onSimStart={(dry) => void orch.onSimStart(dry)}
            onSimStop={() => void orch.onSimStop()}
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
          <BackendTraceVisualizer
            alerts={orch.alerts}
            faultStatus={orch.faultStatus}
            telemetry={telemetry.current}
            historyActions={orch.history?.actions || []}
          />
        </section>

        <aside className="deca-main-right space-y-5">
          <div className="deca-col-label">
            <span className="deca-ps13-tag deca-ps13-tag-q2">Decide</span>
            <span className="deca-ps13-tag deca-ps13-tag-q3">Explain</span>
            <span>Act here</span>
            <span className="deca-col-label-hint">predict → explain → Approve</span>
          </div>

          <AlertRail
            alerts={orch.alerts}
            actionBusy={orch.actionBusy}
            onApprove={(id, path) => void orch.onApprove(id, path)}
            onReject={(id) => void orch.onReject(id)}
            activePath={orch.fleet?.mission?.active_path ?? null}
            mission={orch.fleet?.mission || null}
            sites={orch.fleet?.sites || []}
          />
          <CopilotTerminal
            isAnomaly={telemetry.isAnomaly || hasRaise}
            copilotResponse={telemetry.copilotResponse}
            loading={telemetry.loading}
            source={telemetry.source || 'orchestrator'}
            alerts={orch.alerts}
            modelDetection={orch.faultStatus?.model_detection || null}
            faultPhase={orch.faultStatus?.phase || null}
          />
        </aside>
      </div>

      {orch.error ? (
        <p className="mt-4 text-xs font-mono text-[var(--deca-warn)]">{orch.error}</p>
      ) : null}

      <div className={`deca-term-spacer${demoLive ? ' is-demo' : ''}`} aria-hidden />
      <TerminalDrawer
        faultStatus={orch.faultStatus}
        simulation={orch.simulation}
        demoLive={demoLive}
      />
    </main>
  )
}
