import { X, Beaker, Network, Target, BrainCircuit, Activity } from 'lucide-react'
import { DECA_CITE_BOARD } from '@/lib/cite-board'

export default function MethodologyModal({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-[#1e293b] border border-[#334155] rounded-lg shadow-2xl p-6 lg:p-10 text-[#f8fafc]">
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 p-2 text-[#94a3b8] hover:text-white bg-[#0f172a] rounded-md border border-[#334155]"
        >
          <X className="w-5 h-5" />
        </button>

        <h2 className="text-2xl font-bold mb-2 flex items-center gap-3">
          <Beaker className="text-[#38bdf8]" />
          SD-WAN Predictive Telemetry Methodology
        </h2>
        <p className="text-[#94a3b8] mb-4">
          Validating the mathematical rigor, synthetic ground truth, and SLA benchmarks defining the DECA NOC Copilot.
        </p>
        <p className="mb-8 font-mono text-sm border border-[#334155] bg-[#0f172a] px-3 py-2">
          Cite board (single source): <strong>{DECA_CITE_BOARD.line}</strong>
        </p>

        <div className="grid gap-8 lg:grid-cols-2">
          {/* Benchmarks */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-[#334155]">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Network className="w-4 h-4 text-emerald-400" />
              SLA Benchmarks (The Ground Truth)
            </h3>
            <ul className="space-y-4 text-sm text-[#cbd5e1]">
              <li>
                <strong className="block text-[#f8fafc]">TT&C Mission (Gold)</strong>
                Strict bounds: <code>≤25ms latency</code> · <code>≤5ms jitter</code> · <code>≤0.1% loss</code>. Must never be starved by background traffic.
              </li>
              <li>
                <strong className="block text-[#f8fafc]">Payload (Bronze)</strong>
                Lenient bounds: <code>≤80ms latency</code> · <code>≤2.0% loss</code>.
              </li>
              <li>
                <strong className="block text-[#f8fafc]">Utilization / HTB Ceiling</strong>
                Soft ceiling dynamically policed via Linux HTB tc queues. Predictor flags risk when utilization approaches physical link ceiling, before TT&C queue drops packets.
              </li>
            </ul>
          </section>

          {/* Data Pipeline */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-[#334155]">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              Data Pipeline & Telemetry Corpus
            </h3>
            <ul className="space-y-4 text-sm text-[#cbd5e1]">
              <li>
                <strong className="block text-[#f8fafc]">Hardware Canonical Capture</strong>
                Base L0-L6 corpus scraped via Prometheus from physically isolated Raspberry Pi and GNS3 IPsec topologies. 100% of training data relies on real executed packet paths, not synthesized floats.
              </li>
            </ul>
          </section>

          {/* Routing Decision Architecture */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-[#334155] lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Network className="w-4 h-4 text-[#38bdf8]" />
              Routing Decision Architecture (Who Decides?)
            </h3>
            <p className="text-sm text-[#cbd5e1] mb-4">
              Three separate mechanisms govern path steering. The ML model detects and recommends; it does not execute autonomously.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#1e293b] p-4 rounded border border-[#334155]">
                <h4 className="text-[#f8fafc] font-semibold text-sm mb-2">1. Static Policy</h4>
                <p className="text-xs text-[#94a3b8] leading-relaxed">
                  The mission policy is a fixed priority table (TT&amp;C = CS4/LLQ, Payload = AF41, Admin = BE). When two classes want the same path, "TT&amp;C wins" is a standing rule written into the SD-WAN policy, completely independent of the ML model.
                </p>
              </div>
              
              <div className="bg-[#1e293b] p-4 rounded border border-[#334155]">
                <h4 className="text-[#f8fafc] font-semibold text-sm mb-2">2. Automatic Failover</h4>
                <p className="text-xs text-[#94a3b8] leading-relaxed">
                  Pure threshold logic on RTT/loss probes handles sudden physical link death without waiting on inference. It fails over after 3 consecutive bad probes and fails back after 10 clean ones. This is hard-coded and not AI-driven.
                </p>
              </div>

              <div className="bg-[#1e293b] p-4 rounded border border-[#334155] border-t-2 border-t-[#38bdf8]">
                <h4 className="text-[#f8fafc] font-semibold text-sm mb-2">3. AI-Proposed Steer</h4>
                <p className="text-xs text-[#94a3b8] leading-relaxed">
                  The XGBoost/LSTM models detect degrading conditions and propose an action. Per HITL governance rules (T_breach &lt; 180s warn), a human operator must explicitly click <strong>Approve</strong>. Only then does the orchestrator execute the forced path switch.
                </p>
              </div>
            </div>
          </section>

          {/* ML Validation */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-[#334155] lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Target className="w-4 h-4 text-[#f59e0b]" />
              Model Architecture & Validation Metrics
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#1e293b] p-4 rounded border border-[#334155]">
                <p className="text-xs text-[#94a3b8] uppercase tracking-wide">GNS3 transfer</p>
                <p className="text-3xl font-mono text-white my-2">{DECA_CITE_BOARD.gns3_transfer}</p>
                <p className="text-xs text-[#cbd5e1]">Cross-fabric transfer score (cite board).</p>
              </div>
              <div className="bg-[#1e293b] p-4 rounded border border-[#334155]">
                <p className="text-xs text-[#94a3b8] uppercase tracking-wide">Chaos F1 / Q2 holdout</p>
                <p className="text-3xl font-mono text-white my-2">{DECA_CITE_BOARD.chaos_f1} / {DECA_CITE_BOARD.q2_holdout}</p>
                <p className="text-xs text-[#cbd5e1]">Chaos F1 and Q2 holdout from the sealed cite board.</p>
              </div>
              <div className="bg-[#1e293b] p-4 rounded border border-[#334155]">
                <p className="text-xs text-[#94a3b8] uppercase tracking-wide">Q1 lead / MAE</p>
                <p className="text-3xl font-mono text-white my-2">{DECA_CITE_BOARD.q1_lead_s}s / {DECA_CITE_BOARD.q1_mae}</p>
                <p className="text-xs text-[#cbd5e1]">Mean lead time before breach · MAE on TTI.</p>
              </div>
            </div>
          </section>

          {/* Copilot Pipeline */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-[#334155] lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <BrainCircuit className="w-4 h-4 text-purple-400" />
              Q3 LNC Copilot Pipeline (Phase 4 & 5)
            </h3>
            <p className="text-sm text-[#cbd5e1] mb-4">
              When Q1 and Q2 detect a risk trajectory, the orchestrator triggers a 100% offline Retrieval-Augmented Generation (RAG) pipeline. No cloud dependencies are used.
            </p>
            <div className="flex flex-col md:flex-row gap-4 items-center">
              <div className="flex-1 w-full border border-[#334155] rounded bg-[#1e293b] p-3 text-center text-xs font-mono">
                Mathematical Context<br/><span className="text-[#94a3b8]">ETA, Confidence, Live Prom</span>
              </div>
              <span className="text-[#94a3b8] rotate-90 md:rotate-0">→</span>
              <div className="flex-1 w-full border border-[#334155] rounded bg-[#1e293b] p-3 text-center text-xs font-mono">
                Chroma Vector DB<br/><span className="text-[#94a3b8]">deca_lnc collection</span>
              </div>
              <span className="text-[#94a3b8] rotate-90 md:rotate-0">→</span>
              <div className="flex-1 w-full border border-[#334155] rounded bg-[#1e293b] p-3 text-center text-xs font-mono">
                Ollama Phi-3<br/><span className="text-[#94a3b8]">Generates Operator SOP</span>
              </div>
            </div>
          </section>

          {/* Honesty Disclosure / Gaps */}
          <section className="bg-[#0f172a] p-5 rounded-md border border-rose-500/30 lg:col-span-2">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-rose-400">
              <X className="w-4 h-4" />
              Phase 2 / Scope Limitations (Honesty Disclosure)
            </h3>
            <p className="text-sm text-[#cbd5e1] mb-4">
              To maintain strict evaluation integrity, the following theoretical capabilities are <strong>not claimed</strong> in the current live build and have been intentionally excluded from the dashboard UI:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-sm text-[#94a3b8]">
              <li>Packet-loss progression ML</li>
              <li>IPsec rekey anomaly detection (scoring)</li>
              <li>Path asymmetry detection</li>
              <li>Graph-based multi-signal correlation</li>
              <li>Multi-candidate playbook engine</li>
            </ul>
          </section>

        </div>
      </div>
    </div>
  );
}
