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
    print("Terminal monitors: station1/2/3 + prometheus")
    if collection is None or not config.RUNBOOKS_DIR.is_dir():
        return
    docs, ids = [], []
    for filepath in sorted(config.RUNBOOKS_DIR.glob("*.md")):
        docs.append(filepath.read_text(encoding="utf-8"))
        ids.append(filepath.stem)
    if docs and collection.count() < len(docs):
        collection.upsert(documents=docs, ids=ids)
        print(f"Ingested {len(docs)} runbooks into ChromaDB.")


@app.on_event("shutdown")
def on_shutdown():
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
        from prometheus_feed import fetch_live_network

        fleet = orchestrator.get_fleet()
        live = fetch_live_network()
        stations = live.get("stations") or []
        raw = live.get("raw") or {}
        return sanitize_for_json(
            {
                "source": "prometheus" if live.get("prometheus_reachable") else "orchestrator_light",
                "fabric": live.get("fabric") or fleet.get("fabric"),
                "prometheus": live.get("prometheus") or fleet.get("prometheus"),
                "prometheus_reachable": bool(live.get("prometheus_reachable")),
                "metrics": raw,
                "history": [],
                "stations": stations,
                "prediction": {"predicted_issue": "normal", "confidence_score": 0.0},
                "copilot": _format_copilot(None, {"predicted_issue": "normal"}),
                "fleet": fleet,
                "data": {
                    "prediction": "normal",
                    "anomaly_score": 0.0,
                    "confidence_score": 0.0,
                    "time_to_impact_minutes": None,
                    "contributing_signals": {},
                    "metrics_summary": raw,
                },
                "timestamp": live.get("timestamp"),
                "note": "Light mode: live Prometheus telemetry (ML path needs DECA_HEAVY_INIT=1).",
            }
        )
    try:
        payload = telemetry_service.poll()
        prediction = payload["prediction"]
        try:
            copilot_raw = _run_copilot(prediction)
        except Exception as exc:
            print(f"Warning: copilot failed: {exc}")
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
