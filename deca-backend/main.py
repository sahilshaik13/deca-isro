"""DECA Orchestrator API — FastAPI entrypoint."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import orchestrator
import terminals
from prometheus_feed import sanitize_for_json
from terminal_manager import manager as terminal_manager

app = FastAPI(title="DECA Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Heavy ML / RAG stack — optional (orchestrator ask uses CopilotEngine lazy path).
pipeline = None
telemetry_service = None
llm = None
collection = None
_heavy_error: Optional[str] = None


def strip_llm_reasoning_tags(text: str) -> str:
    patterns = [
        re.escape("<think>") + r".*?" + re.escape("</think>"),
        r"<think>.*?</think>",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def _try_heavy_init() -> None:
    global pipeline, telemetry_service, llm, collection, _heavy_error
    if not config.HEAVY_INIT:
        print("DECA_HEAVY_INIT=0 — skipping eager GGUF/Chroma (orchestrator light mode)")
        return
    try:
        import chromadb
        import numpy as np
        from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
        from chromadb.utils.embedding_functions import register_embedding_function
        from llama_cpp import Llama

        from deca_pipeline import DECAPipeline
        from telemetry_service import TelemetryService

        def load_gguf_model(local_path: str, repo_id: str, filename: str, **kwargs) -> Llama:
            if os.path.isfile(local_path):
                print(f"Using cached model: {local_path}")
                return Llama(model_path=local_path, **kwargs)
            allow = os.environ.get("DECA_ALLOW_HF_DOWNLOAD", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if not allow:
                raise FileNotFoundError(
                    f"GGUF missing at {local_path}. Air-gap mode refuses HuggingFace download."
                )
            os.makedirs(config.MODELS_DIR, exist_ok=True)
            return Llama.from_pretrained(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(config.MODELS_DIR),
                **kwargs,
            )

        print("Initializing ML Pipeline...")
        pipeline = DECAPipeline(models_dir=str(config.MODELS_DIR), seq_len=config.SEQ_LEN)
        telemetry_service = TelemetryService(pipeline)

        print("Loading RAG Embedding Model (MiniLM)...")
        embed_model = load_gguf_model(
            local_path=str(config.MODELS_DIR / config.EMBED_MODEL_FILE),
            repo_id=config.EMBED_MODEL_REPO,
            filename=config.EMBED_MODEL_FILE,
            embedding=True,
            n_ctx=config.EMBED_N_CTX,
            verbose=False,
        )

        if config.LLM_MODEL_FILE:
            print(f"Loading Reasoning Copilot ({config.LLM_MODEL_FILE})...")
            llm = load_gguf_model(
                local_path=str(config.MODELS_DIR / config.LLM_MODEL_FILE),
                repo_id=config.LLM_MODEL_REPO,
                filename=config.LLM_MODEL_FILE,
                n_ctx=config.LLM_N_CTX,
                n_threads=config.LLM_N_THREADS,
                verbose=False,
            )
        else:
            print("No DECA_LLM_MODEL_FILE set — skipping local LLM copilot")
            llm = None

        @register_embedding_function
        class LocalGGUFEmbedding(EmbeddingFunction[Documents]):
            def __init__(self, model: Optional[Llama] = None, model_path: Optional[str] = None) -> None:
                if model is not None:
                    self._model = model
                else:
                    path = model_path or str(config.MODELS_DIR / config.EMBED_MODEL_FILE)
                    self._model = load_gguf_model(
                        local_path=path,
                        repo_id=config.EMBED_MODEL_REPO,
                        filename=config.EMBED_MODEL_FILE,
                        embedding=True,
                        n_ctx=config.EMBED_N_CTX,
                        verbose=False,
                    )

            def __call__(self, input: Documents) -> Embeddings:
                return [np.array(self._model.embed(text), dtype=np.float32) for text in input]

            @staticmethod
            def name() -> str:
                return "local_gguf_minilm"

            @staticmethod
            def build_from_config(cfg: dict[str, Any]) -> "LocalGGUFEmbedding":
                return LocalGGUFEmbedding(model_path=cfg.get("model_path"))

            def get_config(self) -> dict[str, Any]:
                return {"model_path": str(config.MODELS_DIR / config.EMBED_MODEL_FILE)}

        print("Initializing Vector Database...")
        chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        collection = chroma_client.get_or_create_collection(
            name="runbooks",
            embedding_function=LocalGGUFEmbedding(model=embed_model),
        )
    except Exception as exc:  # noqa: BLE001
        _heavy_error = str(exc)
        print(f"Heavy init failed (orchestrator still available): {exc}")


_try_heavy_init()

SYSTEM_PROMPT = """You are an offline NOC copilot for a secure MPLS network.
You ONLY use information provided in CONTEXT. Never invent device names,
IP addresses, VRF names, or AS numbers. If context is insufficient, say so.
Always respond in this JSON format only:
{
  "predicted_issue": "...",
  "confidence_score": 0.XX,
  "time_to_impact_minutes": X,
  "root_cause": "...",
  "affected_scope": ["site", "vrf", "service"],
  "contributing_signals": {"signal_name": contribution_pct},
  "recommended_actions": ["step1", "step2"]
}"""


@app.on_event("startup")
def on_startup():
    orchestrator.bootstrap()
    print(f"SQLite orchestrator DB: {config.SQLITE_PATH}")
    terminal_manager.start()
    try:
        import pipeline_feed

        pipeline_feed.start()
        print("Pipeline feed: inject/telemetry/inference/copilot/decide logs")
    except Exception as exc:  # noqa: BLE001
        print(f"Pipeline feed start failed: {exc}")
    print("Terminal monitors: station1/2/3 + prometheus + pipeline")
    if collection is None or not config.RUNBOOKS_DIR.is_dir():
        return
    docs, ids = [], []
    for filepath in sorted(config.RUNBOOKS_DIR.glob("*.md")):
        docs.append(filepath.read_text(encoding="utf-8"))
        ids.append(filepath.stem)
    if docs:
        # Always refresh so plain-English runbook edits reach RAG immediately.
        collection.upsert(documents=docs, ids=ids)
        print(f"Upserted {len(docs)} runbooks into ChromaDB.")


@app.on_event("shutdown")
def on_shutdown():
    try:
        import pipeline_feed

        pipeline_feed.stop()
    except Exception:  # noqa: BLE001
        pass
    terminal_manager.stop()


app.include_router(orchestrator.router)
app.include_router(terminals.router)


class TelemetryData(BaseModel):
    run_id: str
    metrics: list[dict]


def _format_copilot(copilot_response: dict | None, prediction: dict) -> dict:
    if copilot_response and "error" not in copilot_response:
        return {
            "predicted_issue": copilot_response.get("predicted_issue")
            or prediction.get("predicted_issue"),
            "confidence_score": copilot_response.get("confidence_score")
            if copilot_response.get("confidence_score") is not None
            else prediction.get("confidence_score"),
            "time_to_impact_minutes": copilot_response.get("time_to_impact_minutes")
            if copilot_response.get("time_to_impact_minutes") is not None
            else prediction.get("time_to_impact_minutes"),
            "root_cause": copilot_response.get("root_cause") or prediction.get("root_cause", ""),
            "affected_scope": copilot_response.get("affected_scope")
            or prediction.get("affected_scope")
            or [],
            "contributing_signals": copilot_response.get("contributing_signals")
            or prediction.get("contributing_signals")
            or {},
            "recommended_actions": copilot_response.get("recommended_actions") or [],
            "runbook_steps": copilot_response.get("recommended_actions") or [],
            "mitigation_checklist": copilot_response.get("recommended_actions") or [],
        }
    signals = prediction.get("contributing_signals") or {}
    if prediction.get("predicted_issue") not in (None, "normal", "healthy", "INSUFFICIENT_CONTEXT"):
        return {
            "predicted_issue": prediction.get("predicted_issue"),
            "confidence_score": prediction.get("confidence_score"),
            "time_to_impact_minutes": prediction.get("time_to_impact_minutes"),
            "root_cause": prediction.get("root_cause")
            or (f"Top signals: {', '.join(signals.keys())}" if signals else ""),
            "affected_scope": prediction.get("affected_scope") or [],
            "contributing_signals": signals,
            "recommended_actions": prediction.get("recommended_actions") or [],
            "runbook_steps": prediction.get("recommended_actions") or [],
            "mitigation_checklist": prediction.get("recommended_actions") or [],
        }
    # Light-mode / idle prediction — still explain from an open Decide card if present.
    decide = _copilot_from_open_decide()
    if decide:
        return decide
    return {
        "predicted_issue": prediction.get("predicted_issue", "normal"),
        "confidence_score": prediction.get("confidence_score", 0.0),
        "time_to_impact_minutes": prediction.get("time_to_impact_minutes"),
        "root_cause": "Monitoring live telemetry — no anomaly flagged.",
        "affected_scope": [],
        "contributing_signals": signals,
        "recommended_actions": [],
        "runbook_steps": [],
        "mitigation_checklist": [],
    }


_IDLE_COPILOT = "Monitoring live telemetry — no anomaly flagged."

_PLAIN_CLASS = {
    "congestion_breach": "Congestion — mission traffic at risk",
    "tunnel_degradation": "Primary path degrading (latency / loss)",
    "bgp_route_flap": "Routing unstable — paths flapping",
    "vrf_leakage": "Network isolation broken",
    "policy_drift": "Traffic policy drifted from the plan",
}


def _copilot_from_model_detection(st: dict) -> dict | None:
    """Narrate from live Q1/Q2 oneshot on the fault demo — not from inject script id."""
    md = st.get("model_detection")
    if not isinstance(md, dict) or not md.get("ok"):
        return None
    sev = str(md.get("severity") or "0").strip() or "0"
    raised = bool(md.get("raise")) or (sev != "0")
    if not raised:
        return None

    conf = md.get("q2_confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.7
    except (TypeError, ValueError):
        conf_f = 0.7
    eta = md.get("eta_minutes")
    try:
        eta_f = float(eta) if eta is not None else None
    except (TypeError, ValueError):
        eta_f = None

    expl = str(md.get("explanation") or "").strip()
    name_bits = []
    if sev != "0":
        name_bits.append(f"Q2 severity {sev}")
    if eta_f is not None:
        name_bits.append(f"Q1 TTI ≈ {eta_f:.2f} min")
    if md.get("eta_source"):
        name_bits.append(f"eta_source={md.get('eta_source')}")
    head = "Model scores: " + (", ".join(name_bits) if name_bits else "anomaly")
    root_cause = f"{head}. {expl}".strip() if expl else head
    root_cause += " Copilot grounds runbooks on these scores once Decide raises."

    return {
        "predicted_issue": "anomaly_detected",
        "confidence_score": conf_f,
        "time_to_impact_minutes": eta_f,
        "root_cause": root_cause,
        "affected_scope": [],
        "contributing_signals": {
            "q2_confidence": conf_f,
            **({"q1_eta_minutes": eta_f} if eta_f is not None else {}),
        },
        "recommended_actions": [
            "Wait for / open the Decide card built from these model scores",
            "Approve backup to steer off the preferred path",
            "Or wait — inject auto-heals after the hold if you do not Approve",
        ],
        "runbook_steps": [
            "Confirm live Prom matches the model fingerprint (latency, loss, CPU, flaps)",
            "Read Decide title / severity / ETA from Q1+Q2 (not the inject button name)",
            "Approve backup to complete HITL steer",
        ],
        "mitigation_checklist": [
            "Approve backup on Decide",
            "Confirm path / underlay badge updates",
            "Confirm Decide / Copilot idle after steer",
        ],
    }


def _copilot_from_open_decide() -> dict | None:
    """Build Copilot text from model Decide / live Q1+Q2 — never from inject script labels."""
    try:
        import repos
    except Exception:  # noqa: BLE001
        return None

    alert = None
    try:
        for a in repos.list_alerts(status="active", limit=30):
            payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
            cls = a.get("class") or ""
            if payload.get("preemption") or payload.get("noc_demo_fault") or cls in _FAULT_CLASSES:
                alert = a
                break
    except Exception:  # noqa: BLE001
        return None

    # Prefer an open Decide card (already model-seeded).
    if alert:
        payload = alert.get("payload") if isinstance(alert.get("payload"), dict) else {}
        cls = str(alert.get("class") or "")
        title = str(
            payload.get("title") or _PLAIN_CLASS.get(cls) or cls.replace("_", " ") or "Network risk"
        )
        q3 = str(payload.get("q3_nlp") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        root = str(payload.get("root_cause") or "").replace("_", " ").strip()
        md = payload.get("model_detection") if isinstance(payload.get("model_detection"), dict) else {}
        eta = alert.get("eta")
        if eta is None:
            eta = payload.get("eta_minutes")

        if q3:
            root_cause = q3
        else:
            bits = [title]
            if root:
                bits.append(f"Model class: {root}.")
            if md.get("severity"):
                bits.append(f"Q2 severity={md.get('severity')} (p={md.get('q2_confidence')}).")
            if summary:
                bits.append(summary)
            if eta is not None:
                try:
                    bits.append(f"Q1 predicted impact in about {float(eta):.1f} minutes.")
                except (TypeError, ValueError):
                    pass
            if payload.get("eta_source"):
                bits.append(f"(eta_source={payload.get('eta_source')})")
            bits.append("Next step: Approve backup on the Decide card (or wait for auto-heal).")
            root_cause = " ".join(bits)

        actions: list[str] = []
        raw_actions = payload.get("recommended_actions")
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if isinstance(item, dict):
                    label = item.get("label") or item.get("action") or item.get("op")
                    if label:
                        actions.append(str(label))
                elif item:
                    actions.append(str(item))
        concerns = payload.get("concerns")
        if isinstance(concerns, list):
            for c in concerns:
                if c and str(c) not in actions:
                    actions.append(str(c))
        if not actions:
            actions = [
                "Review Decide prediction and model confidence",
                "Approve backup to steer traffic off the failing path",
                "Or wait — demo faults auto-heal after the hold window",
            ]

        runbook = [
            "Confirm live metrics match the model class (latency, loss, CPU, or flaps)",
            "Read why this matters on the Decide card (Q1 ETA / Q2 severity)",
            "Click Approve backup to steer and stop the inject",
        ]
        checklist = [
            "Approve backup on Decide",
            "Confirm underlay / path badge updates",
            "Confirm alerts clear after steer or auto-heal",
        ]

        conf = alert.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.85
        except (TypeError, ValueError):
            conf_f = 0.85
        try:
            eta_f = float(eta) if eta is not None else None
        except (TypeError, ValueError):
            eta_f = None

        return {
            "predicted_issue": cls or "anomaly_detected",
            "confidence_score": conf_f,
            "time_to_impact_minutes": eta_f,
            "root_cause": root_cause,
            "affected_scope": list(payload.get("affected_scope") or []),
            "contributing_signals": dict(payload.get("contributing_signals") or {}),
            "recommended_actions": actions[:8],
            "runbook_steps": runbook,
            "mitigation_checklist": checklist,
        }

    # No Decide yet — only speak if live oneshot already crossed the score gate.
    try:
        import fault_demo

        st = fault_demo.status()
        from_model = _copilot_from_model_detection(st)
        if from_model:
            return from_model
        # Inject running but model has not raised — stay quiet (do not name the script).
        if st.get("fault_id") and st.get("phase") in (
            "injecting",
            "seeded",
            "collapsing",
            "recovering",
        ):
            return None
    except Exception:  # noqa: BLE001
        pass
    return None


_FAULT_CLASSES = {
    "congestion_breach",
    "tunnel_degradation",
    "bgp_route_flap",
    "vrf_leakage",
    "policy_drift",
    "anomaly_detected",
}


def _run_copilot(prediction: dict) -> dict | None:
    if llm is None or collection is None:
        return None
    issue = prediction.get("predicted_issue") or ""
    if issue in ("normal", "healthy", "INSUFFICIENT_CONTEXT", ""):
        return None

    signals = prediction.get("contributing_signals", {})
    query = f"SOP for {issue} network fault"
    results = collection.query(query_texts=[query], n_results=2)
    docs = []
    if results.get("documents") and results["documents"][0]:
        docs = results["documents"][0]
    retrieved_doc = "\n---\n".join(docs) if docs else "No matching runbook found."

    context = f"""
ML PREDICTION (promoted live stack):
  Predicted issue: {issue}
  Confidence: {prediction.get('confidence_score')}
  Time to impact (minutes): {prediction.get('time_to_impact_minutes')}
  Affected scope: {prediction.get('affected_scope')}
  Contributing signals: {signals}

RETRIEVED INTERNAL ARTIFACTS:
  {retrieved_doc}
"""
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        temperature=0.2,
        max_tokens=500,
    )

    raw_output = response["choices"][0]["message"]["content"]
    clean_output = strip_llm_reasoning_tags(raw_output)
    clean_output = clean_output.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(clean_output)
        parsed["predicted_issue"] = issue
        if prediction.get("confidence_score") is not None:
            parsed.setdefault("confidence_score", prediction["confidence_score"])
        if prediction.get("time_to_impact_minutes") is not None:
            parsed.setdefault("time_to_impact_minutes", prediction["time_to_impact_minutes"])
        if prediction.get("affected_scope"):
            parsed.setdefault("affected_scope", prediction["affected_scope"])
        return parsed
    except json.JSONDecodeError:
        return {"error": "Failed to parse copilot JSON", "raw": clean_output}


@app.get("/")
def read_root():
    return {
        "status": "DECA Orchestrator API is running",
        "product": "DECA",
        "api_base_url": config.API_BASE_URL,
        "host": config.HOST,
        "port": config.PORT,
        "sqlite": str(config.SQLITE_PATH),
        "heavy_init": bool(pipeline is not None),
        "heavy_error": _heavy_error,
    }


@app.get("/health")
def health():
    return {"status": "ok", "product": "DECA Orchestrator"}


@app.get("/api/v1/dashboard")
def get_dashboard():
    if telemetry_service is None:
        # Orchestrator-light: live Prom network snapshot (no ML/GGUF required)
        from prometheus_feed import fetch_live_network, raw_to_display

        # One Prom scrape (cached) shared with get_fleet.
        live = fetch_live_network()
        fleet = orchestrator.get_fleet()
        stations = live.get("stations") or []
        raw = live.get("raw") or {}
        ts = str(live.get("timestamp") or "")
        display = live.get("metrics") or raw_to_display(raw, ts)
        history = live.get("history") or ([display] if display else [])
        decide_copilot = _copilot_from_open_decide()
        prediction = {
            "predicted_issue": (
                decide_copilot.get("predicted_issue")
                if decide_copilot
                else "normal"
            ),
            "confidence_score": (
                float(decide_copilot.get("confidence_score") or 0.0)
                if decide_copilot
                else 0.0
            ),
            "time_to_impact_minutes": (
                decide_copilot.get("time_to_impact_minutes") if decide_copilot else None
            ),
            "root_cause": (decide_copilot or {}).get("root_cause") or "",
            "recommended_actions": (decide_copilot or {}).get("recommended_actions") or [],
            "contributing_signals": (decide_copilot or {}).get("contributing_signals") or {},
        }
        return sanitize_for_json(
            {
                "source": "prometheus" if live.get("prometheus_reachable") else "orchestrator_light",
                "fabric": live.get("fabric") or fleet.get("fabric"),
                "prometheus": live.get("prometheus") or fleet.get("prometheus"),
                "prometheus_reachable": bool(live.get("prometheus_reachable")),
                "metrics": display,
                "history": history,
                "stations": stations,
                "prediction": prediction,
                "copilot": decide_copilot
                or _format_copilot(None, {"predicted_issue": "normal"}),
                "fleet": fleet,
                "data": {
                    "prediction": prediction.get("predicted_issue") or "normal",
                    "anomaly_score": float(prediction.get("confidence_score") or 0.0),
                    "confidence_score": float(prediction.get("confidence_score") or 0.0),
                    "time_to_impact_minutes": prediction.get("time_to_impact_minutes"),
                    "contributing_signals": prediction.get("contributing_signals") or {},
                    "metrics_summary": display,
                },
                "timestamp": live.get("timestamp"),
                "last_updated": live.get("timestamp"),
                "note": "Light mode: live Prometheus telemetry (ML path needs DECA_HEAVY_INIT=1).",
            }
        )
    try:
        payload = telemetry_service.poll()
        prediction = payload["prediction"]
        copilot_raw = None
        payload["copilot"] = _format_copilot(copilot_raw, prediction)
        payload["data"] = {
            "prediction": prediction.get("predicted_issue", "normal"),
            "anomaly_score": prediction.get("confidence_score", 0.0),
            "confidence_score": prediction.get("confidence_score", 0.0),
            "time_to_impact_minutes": prediction.get("time_to_impact_minutes"),
            "contributing_signals": prediction.get("contributing_signals", {}),
            "metrics_summary": payload["metrics"],
        }
        try:
            payload["fleet"] = orchestrator.get_fleet()
        except Exception:
            payload["fleet"] = None
        return sanitize_for_json(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/v1/predict")
def get_prediction(data: TelemetryData):
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="ML pipeline not loaded. Set DECA_HEAVY_INIT=1.",
        )
    try:
        import pandas as pd

        df = pd.DataFrame(data.metrics)
        prediction = pipeline.predict(df)
        copilot_raw = _run_copilot(prediction)
        return {
            "success": True,
            "data": prediction,
            "copilot": _format_copilot(copilot_raw, prediction),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
    )
