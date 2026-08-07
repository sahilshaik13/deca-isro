'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp, Wrench } from 'lucide-react'
import FabricSelect from '@/components/noc/FabricSelect'
import TrafficButtons from '@/components/noc/TrafficButtons'
import FaultButtons from '@/components/noc/FaultButtons'
import SimulationControl from '@/components/noc/SimulationControl'
import type { FabricId, FabricStatus, FaultDemoStatus, SimulationStatus, TrafficStatus } from '@/lib/api'

type Props = {
  fabricStatus: FabricStatus | null
  fabricBusy: boolean
  onFabricSelect: (id: FabricId) => void
  trafficStatus: TrafficStatus | null
  trafficBusy: boolean
  activeFabric: string
  onTrafficStart: (profile: string) => void
  onTrafficStop: () => void
  faultStatus: FaultDemoStatus | null
  faultBusy: boolean
  onFaultStart: (id: string) => void
  onFaultClear: () => void
  simulation: SimulationStatus | null
  simBusy: boolean
  onSimStart: (dry: boolean) => void
  onSimStop: () => void
}

export default function LabControls(props: Props) {
  const [open, setOpen] = useState(true)
  const running =
    Boolean(props.faultStatus?.running) ||
    Boolean(props.simulation?.running) ||
    Boolean(props.trafficStatus?.running)

  return (
    <section className="deca-panel deca-lab-controls">
      <button
        type="button"
        className="deca-lab-controls-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="deca-lab-controls-title">
          <Wrench className="w-3.5 h-3.5" />
          <div>
            <h2 className="deca-section-title">Demo controls</h2>
            <p className="deca-section-sub">
              Start here: pick a fault below. Left shows the network reacting; right asks you to Approve.
            </p>
          </div>
        </div>
        <span className="deca-lab-controls-meta">
          {running ? <span className="deca-pill deca-pill-warn">live</span> : null}
          {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </span>
      </button>

      {open ? (
        <div className="deca-lab-controls-body">
          <div className="deca-lab-slot">
            <FabricSelect
              embedded
              status={props.fabricStatus}
              busy={props.fabricBusy || props.faultBusy || props.trafficBusy}
              onSelect={props.onFabricSelect}
            />
          </div>
          <div className="deca-lab-slot">
            <TrafficButtons
              embedded
              status={props.trafficStatus}
              busy={props.trafficBusy}
              fabric={props.activeFabric}
              onStart={props.onTrafficStart}
              onStop={props.onTrafficStop}
            />
          </div>
          <div className="deca-lab-slot">
            <FaultButtons
              embedded
              status={props.faultStatus}
              busy={props.faultBusy}
              fabric={props.activeFabric}
              onStart={props.onFaultStart}
              onClear={props.onFaultClear}
            />
          </div>
          <div className="deca-lab-slot">
            <SimulationControl
              embedded
              status={props.simulation}
              busy={props.simBusy}
              onStart={props.onSimStart}
              onStop={props.onSimStop}
            />
          </div>
        </div>
      ) : null}
    </section>
  )
}
