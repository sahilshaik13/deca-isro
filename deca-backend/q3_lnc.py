"""Q3 LNC copilot: Prom snapshot + Chroma retrieve + optional Phi-3.

Math gate (Q1/Q2 → seed-preemption) must NOT wait on this module.
Enrichment runs in a background thread and merges `q3_nlp` onto the alert.

Chroma access prefers an in-process chromadb import; if missing, falls back to
`~/deca-copilot/.venv/bin/python` + `q3_explain_cli.py` so the orchestrator
venv does not need chromadb installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import requests

DEFAULT_CHROMA = Path(
    os.environ.get(
        "DECA_LNC_CHROMA",
        str(Path.home() / "deca-copilot" / "chroma_lnc"),
    )
).expanduser()
COLLECTION = os.environ.get("DECA_LNC_COLLECTION", "deca_lnc")
OLLAMA_URL = os.environ.get("DECA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.environ.get("DECA_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.environ.get("DECA_CHAT_MODEL", "phi3")
PROM_URL = os.environ.get("DECA_PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
# Prefer deca-copilot venv (chromadb 1.x matching the LNC store).
COPILOT_PY = os.environ.get(
    "DECA_COPILOT_PYTHON",
    str(Path.home() / "deca-copilot" / ".venv" / "bin" / "python"),
)
COPILOT_CLI = os.environ.get(
    "DECA_Q3_CLI",
    str(Path.home() / "deca-copilot" / "q3_explain_cli.py"),
)

SNAPSHOT_QUERIES: dict[str, str] = {
    "latency_gre_ms": 'sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}',
    "latency_eth0_ms": 'sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="eth0",src="edge"}',
    "jitter_gre_ms": 'sdwan_path_jitter_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre"}',
    "loss_gre_pct": 'sdwan_path_loss_pct{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}',
    "cpu_usage_system": 'cpu_usage_system{job="deca_kafka_telemetry_bridge",host="station1"}',
    "cpu_usage_user": 'cpu_usage_user{job="deca_kafka_telemetry_bridge",host="station1"}',
    "mem_used_percent": 'mem_used_percent{job="deca_kafka_telemetry_bridge",host="station1"}',
    "bgp_flap_count": 'bgp_flap_count{job="deca_kafka_telemetry_bridge",host="station1"}',
}

_vs_lock = threading.Lock()
_collection = None


def prom_snapshot(prom_url: str = PROM_URL, timeout: float = 3.0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, promql in SNAPSHOT_QUERIES.items():
        try:
            resp = requests.get(
                f"{prom_url}/api/v1/query",
                params={"query": promql},
                timeout=timeout,
            )
            resp.raise_for_status()
            results = resp.json().get("data", {}).get("result", [])
            if not results:
                out[name] = None
                continue
            out[name] = float(results[0]["value"][1])
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
            out[name] = None
    return out


def _embed(texts: list[str], *, ollama: str = OLLAMA_URL, model: str = EMBED_MODEL) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        resp = requests.post(
            f"{ollama}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        vectors.append(resp.json()["embedding"])
    return vectors


def _get_collection(chroma_dir: Path = DEFAULT_CHROMA):
    global _collection
    with _vs_lock:
        if _collection is not None:
            return _collection
        import chromadb

        client = chromadb.PersistentClient(path=str(chroma_dir))
        _collection = client.get_or_create_collection(COLLECTION)
        return _collection


def retrieve_lnc(
    query: str,
    *,
    k: int = 4,
    chroma_dir: Path = DEFAULT_CHROMA,
) -> list[dict[str, Any]]:
    col = _get_collection(chroma_dir)
    emb = _embed([query])[0]
    res = col.query(
        query_embeddings=[emb],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    hits: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        hits.append(
            {
                "text": doc,
                "source": (metas[i] or {}).get("source", "?"),
                "distance": dists[i] if i < len(dists) else None,
            }
        )
    return hits


def _ollama_generate(prompt: str, *, model: str = CHAT_MODEL, ollama: str = OLLAMA_URL) -> str:
    resp = requests.post(
        f"{ollama}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=180,
    )
    resp.raise_for_status()
    return str(resp.json().get("response") or "").strip()


def build_math_query(math: dict[str, Any], snapshot: dict[str, Any]) -> str:
    parts = [
        str(math.get("title") or ""),
        str(math.get("summary") or ""),
        str(math.get("root_cause") or ""),
        str(math.get("severity") or ""),
        str(math.get("alert_class") or ""),
    ]
    if snapshot.get("latency_gre_ms") is not None:
        parts.append(f"GRE latency {snapshot['latency_gre_ms']} ms")
    if snapshot.get("latency_eth0_ms") is not None:
        parts.append(f"eth0 latency {snapshot['latency_eth0_ms']} ms")
    if snapshot.get("cpu_usage_user") is not None:
        parts.append(f"CPU user {snapshot['cpu_usage_user']}")
    if snapshot.get("bgp_flap_count") is not None:
        parts.append(f"BGP flaps {snapshot['bgp_flap_count']}")
    parts.append("TT&C SLA preemption steer PE1")
    return " ".join(p for p in parts if p).strip()


def _explain_via_subprocess(math_context: dict[str, Any], *, use_llm: bool) -> dict[str, Any]:
    py = Path(COPILOT_PY)
    cli = Path(COPILOT_CLI)
    if not py.is_file() or not cli.is_file():
        return {
            "ok": False,
            "error": "copilot_subprocess_missing",
            "q3_nlp": "",
            "sources": [],
            "prom_snapshot": prom_snapshot(),
        }
    cmd = [str(py), str(cli), "--math-json", "-"]
    cmd.append("--use-llm" if use_llm else "--no-llm")
    env = os.environ.copy()
    env["DECA_Q3_NO_SUBPROCESS"] = "1"
    proc = subprocess.run(
        cmd,
        input=json.dumps(math_context).encode(),
        capture_output=True,
        timeout=240,
        env=env,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"subprocess_rc_{proc.returncode}:{proc.stderr.decode()[:300]}",
            "q3_nlp": "",
            "sources": [],
            "prom_snapshot": {},
        }
    return json.loads(proc.stdout.decode() or "{}")


def explain(
    math_context: dict[str, Any],
    *,
    prom_url: str = PROM_URL,
    use_llm: bool = True,
    k: int = 4,
    chroma_dir: Path = DEFAULT_CHROMA,
) -> dict[str, Any]:
    """Return Q3 payload: retrieval + optional English NLP (does not raise to caller)."""
    if os.environ.get("DECA_Q3_NO_SUBPROCESS") != "1":
        try:
            import chromadb

            # LangChain LNC store needs chromadb 1.x; 0.6 in-process breaks with `_type`.
            ver = getattr(chromadb, "__version__", "0")
            major = int(str(ver).split(".", 1)[0] or "0")
            if major < 1:
                return _explain_via_subprocess(math_context, use_llm=use_llm)
        except ImportError:
            return _explain_via_subprocess(math_context, use_llm=use_llm)
        except Exception:
            return _explain_via_subprocess(math_context, use_llm=use_llm)

    snapshot = prom_snapshot(prom_url)
    query = build_math_query(math_context, snapshot)
    try:
        hits = retrieve_lnc(query, k=k, chroma_dir=chroma_dir)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"retrieve_failed:{exc}",
            "prom_snapshot": snapshot,
            "query": query,
            "q3_nlp": "",
            "sources": [],
        }

    sources = [h.get("source") for h in hits]
    context = "\n\n---\n\n".join(
        f"SOURCE: {h.get('source')}\n{h.get('text')}" for h in hits
    )
    snap_txt = json.dumps(snapshot, indent=2)
    math_txt = json.dumps(math_context, indent=2, default=str)

    if not use_llm:
        bullets = []
        for h in hits[:3]:
            line = (h.get("text") or "").strip().splitlines()
            title = next((ln for ln in line if ln.startswith("#")), h.get("source"))
            bullets.append(f"- {title}")
        nlp = (
            "Q3 retrieve-only (Phi-3 skipped). Math context + LNC hits:\n"
            + "\n".join(bullets)
            + f"\nProm snapshot: GRE={snapshot.get('latency_gre_ms')} ms "
            f"eth0={snapshot.get('latency_eth0_ms')} ms "
            f"CPU_user={snapshot.get('cpu_usage_user')}."
        )
        return {
            "ok": True,
            "q3_nlp": nlp,
            "prom_snapshot": snapshot,
            "sources": sources,
            "query": query,
            "generation_path": "q3_retrieve_only",
        }

    prompt = f"""You are the DECA SD-WAN NOC Copilot (Q3). The math gate already alerted the operator.
Use ONLY the Local Network Context and the live Prom snapshot. Be brief and actionable.
Do not invent metrics. Recommend Approve/Reject wording for the Decide rail (steer on PE1).

MATH ALERT (Q1/Q2):
{math_txt}

LIVE PROM SNAPSHOT:
{snap_txt}

LOCAL NETWORK CONTEXT:
{context}

Write 4-8 sentences: what is happening, which SOP applies, what Approve will do, what to watch after."""

    try:
        nlp = _ollama_generate(prompt)
        path = "q3_phi3_rag"
    except Exception as exc:  # noqa: BLE001
        nlp = (
            f"Q3 LLM unavailable ({exc}). Retrieved LNC from: "
            f"{', '.join(str(s) for s in sources)}. "
            f"GRE={snapshot.get('latency_gre_ms')} ms eth0={snapshot.get('latency_eth0_ms')} ms. "
            "Approve still steers via controller on PE1; do not wait on NLP."
        )
        path = f"q3_retrieve_fallback:{exc}"

    return {
        "ok": True,
        "q3_nlp": nlp,
        "prom_snapshot": snapshot,
        "sources": sources,
        "query": query,
        "generation_path": path,
    }


def enrich_alert_async(
    alert_id: int,
    math_context: dict[str, Any],
    *,
    use_llm: bool = True,
    prom_url: str = PROM_URL,
) -> None:
    """Background: explain + merge onto alert payload. Never blocks the math gate."""

    def _run() -> None:
        try:
            import repos

            result = explain(math_context, prom_url=prom_url, use_llm=use_llm)
            patch = {
                "q3_nlp": result.get("q3_nlp") or "",
                "q3_sources": result.get("sources") or [],
                "q3_prom_snapshot": result.get("prom_snapshot") or {},
                "q3_generation_path": result.get("generation_path") or "",
                "q3_ok": bool(result.get("ok")),
                "q3_pending": False,
            }
            if result.get("error"):
                patch["q3_error"] = result["error"]
            repos.merge_alert_payload(alert_id, patch)
        except Exception as exc:  # noqa: BLE001
            print(f"[q3_lnc] enrich alert {alert_id} failed: {exc}")

    threading.Thread(target=_run, name=f"q3-enrich-{alert_id}", daemon=True).start()
