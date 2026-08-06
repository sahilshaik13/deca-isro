import { X, Beaker, Network, Target, BrainCircuit, Activity } from 'lucide-react'

export default function MethodologyModal({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-[var(--deca-panel-1,#1e293b)] border border-[var(--deca-border,#334155)] rounded-lg shadow-2xl p-6 lg:p-10 text-[var(--deca-text,#f8fafc)]">
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 p-2 text-[var(--deca-mute,#94a3b8)] hover:text-white bg-[var(--deca-panel-2,#0f172a)] rounded-md border border-[var(--deca-border,#334155)]"
        >
          <X className="w-5 h-5" />
        </button>

        <h2 className="text-2xl font-bold mb-2 flex items-center gap-3">
          <Beaker className="text-[var(--deca-primary,#38bdf8)]" />
          SD-WAN Predictive Telemetry Methodology
        </h2>
        <p className="text-[var(--deca-mute,#94a3b8)] mb-8">
          Validating the mathematical rigor, synthetic ground truth, and SLA benchmarks defining the DECA NOC Copilot.
        </p>

        <div className="grid gap-8 lg:grid-cols-2">
          {/* Benchmarks */}
          <section className="bg-[var(--deca-panel-2,#0f172a)] p-5 rounded-md border border-[var(--deca-border,#334155)]">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Network className="w-4 h-4 text-emerald-400" />
              SLA Benchmarks (The Ground Truth)
            </h3>
            <ul className="space-y-4 text-sm text-[var(--deca-text-dim,#cbd5e1)]">
              <li>
                <strong className="block text-[var(--deca-text,#f8fafc)]">TT&C Mission (Gold)</strong>
                Strict bounds: <code>≤25ms latency</code> · <code>≤5ms jitter</code> · <code>≤0.1% loss</code>. Must never be starved by background traffic.
              </li>
              <li>
                <strong className="block text-[var(--deca-text,#f8fafc)]">Payload (Bronze)</strong>
                Lenient bounds: <code>≤80ms latency</code> · <code>≤2.0% loss</code>.
              </li>
              <li>
                <strong className="block text-[var(--deca-text,#f8fafc)]">Utilization / HTB Ceiling</strong>
                Soft ceiling dynamically policed via Linux HTB tc queues. Predictor flags risk when utilization approaches physical link ceiling, before TT&C queue drops packets.
              </li>
            </ul>
          </section>

          {/* Synthetic Data */}
          <section className="bg-[var(--deca-panel-2,#0f172a)] p-5 rounded-md border border-[var(--deca-border,#334155)]">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              Data Pipeline & Synthetic Bridge
            </h3>
            <ul className="space-y-4 text-sm text-[var(--deca-text-dim,#cbd5e1)]">
              <li>
                <strong className="block text-[var(--deca-text,#f8fafc)]">Hardware Canonical Capture</strong>
                Base L0 corpus scraped via Prometheus from physically isolated Raspberry Pi and GNS3 IPsec topologies.
              </li>
              <li>
                <strong className="block text-[var(--deca-text,#f8fafc)]">Synthetic Gaps Addressed</strong>
                L3 BGP Route Flaps and L5 Utilization Congestion (HTB) were mathematically synthesized and merged to overcome hardware emulation constraints, yielding <code className="text-xs">synth_merged_new</code>.
              </li>
            </ul>
          </section>

          {/* ML Validation */}
          <section className="bg-[var(--deca-panel-2,#0f172a)] p-5 rounded-md border border-[var(--deca-border,#334155)] lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Target className="w-4 h-4 text-[var(--deca-warn,#f59e0b)]" />
              Model Architecture & Validation Metrics
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[var(--deca-panel-1,#1e293b)] p-4 rounded border border-[var(--deca-border,#334155)]">
                <p className="text-xs text-[var(--deca-mute,#94a3b8)] uppercase tracking-wide">Q2 Severity (XGBoost)</p>
                <p className="text-3xl font-mono text-white my-2">97.64%</p>
                <p className="text-xs text-[var(--deca-text-dim,#cbd5e1)]">Holdout split accuracy. Target was ≥90%. Predicts exact SLA fault class.</p>
              </div>
              <div className="bg-[var(--deca-panel-1,#1e293b)] p-4 rounded border border-[var(--deca-border,#334155)]">
                <p className="text-xs text-[var(--deca-mute,#94a3b8)] uppercase tracking-wide">Q2 Root-Cause (XGBoost)</p>
                <p className="text-3xl font-mono text-white my-2">99.63%</p>
                <p className="text-xs text-[var(--deca-text-dim,#cbd5e1)]">Validates multi-class labels (e.g. ce_sla_conflict vs bgp_flap).</p>
              </div>
              <div className="bg-[var(--deca-panel-1,#1e293b)] p-4 rounded border border-[var(--deca-border,#334155)]">
                <p className="text-xs text-[var(--deca-mute,#94a3b8)] uppercase tracking-wide">Q1 TTI / ETA (LSTM)</p>
                <p className="text-3xl font-mono text-white my-2">50.2s</p>
                <p className="text-xs text-[var(--deca-text-dim,#cbd5e1)]">Mean Absolute Error (MAE) predicting time-to-impact before hard SLA breach.</p>
              </div>
            </div>
          </section>

          {/* Copilot Pipeline */}
          <section className="bg-[var(--deca-panel-2,#0f172a)] p-5 rounded-md border border-[var(--deca-border,#334155)] lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <BrainCircuit className="w-4 h-4 text-purple-400" />
              Q3 LNC Copilot Pipeline (Phase 4 & 5)
            </h3>
            <p className="text-sm text-[var(--deca-text-dim,#cbd5e1)] mb-4">
              When Q1 and Q2 detect a risk trajectory, the orchestrator triggers a 100% offline Retrieval-Augmented Generation (RAG) pipeline. No cloud dependencies are used.
            </p>
            <div className="flex flex-col md:flex-row gap-4 items-center">
              <div className="flex-1 w-full border border-[var(--deca-border,#334155)] rounded bg-[var(--deca-panel-1,#1e293b)] p-3 text-center text-xs font-mono">
                Mathematical Context<br/><span className="text-[var(--deca-mute,#94a3b8)]">ETA, Confidence, Live Prom</span>
              </div>
              <span className="text-[var(--deca-mute,#94a3b8)] rotate-90 md:rotate-0">→</span>
              <div className="flex-1 w-full border border-[var(--deca-border,#334155)] rounded bg-[var(--deca-panel-1,#1e293b)] p-3 text-center text-xs font-mono">
                Chroma Vector DB<br/><span className="text-[var(--deca-mute,#94a3b8)]">deca_lnc collection</span>
              </div>
              <span className="text-[var(--deca-mute,#94a3b8)] rotate-90 md:rotate-0">→</span>
              <div className="flex-1 w-full border border-[var(--deca-border,#334155)] rounded bg-[var(--deca-panel-1,#1e293b)] p-3 text-center text-xs font-mono">
                Ollama Phi-3<br/><span className="text-[var(--deca-mute,#94a3b8)]">Generates Operator SOP</span>
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  );
}
