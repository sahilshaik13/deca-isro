"""Ask-path: reuse test-zone intent + CopilotEngine(skip_rag=True)."""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any, Optional

import config

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_engine = None
_engine_lock = threading.Lock()
_engine_error: Optional[str] = None


def get_copilot_engine():
    """Lazy singleton CopilotEngine with RAG skipped (orchestrator honesty)."""
    global _engine, _engine_error
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_error:
            return None
        try:
            from deca_copilot_bridge import CopilotEngine  # noqa: WPS433

            _engine = CopilotEngine(skip_rag=bool(config.COPILOT_SKIP_RAG))
            return _engine
        except Exception as exc:  # noqa: BLE001
            _engine_error = str(exc)
            print(f"[orchestrator] CopilotEngine unavailable: {exc}")
            return None


def run_ask(
    question: str,
    *,
    run_id: Optional[str],
) -> dict[str, Any]:
    """Answer an operator question; returns answer + intent + path for SQLite."""
    from deca_live_common import declarations_path, live_run_dir  # noqa: WPS433
    from deca_test_zone import (  # noqa: WPS433
        assemble_payload,
        extract_intent_llm,
        extract_intent_rules,
        fetch_model_values,
        format_final_answer,
        load_declarations,
    )

    ns = argparse.Namespace(live=not bool(run_id), replay=run_id, run_id=run_id)
    mode = "replay" if run_id else "live"
    decl_file: Optional[Path] = None
    feed_path: Optional[Path] = None
    try:
        from deca_test_zone import resolve_data_source  # noqa: WPS433

        rid, decl_file = resolve_data_source(ns)
        mode = rid
        feed_path = live_run_dir(rid) / "operator_feed.log"
        if not feed_path.is_file():
            feed_path = None
    except SystemExit as exc:
        if run_id:
            decl_file = declarations_path(run_id)
            feed_cand = live_run_dir(run_id) / "operator_feed.log"
            feed_path = feed_cand if feed_cand.is_file() else None
        else:
            return {
                "answer": f"No live operator run available ({exc}). Bind a run_id first.",
                "intent": {"confident": False},
                "generation_path": "no_data_source",
                "mode": mode,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "answer": f"Could not resolve operator data: {exc}",
            "intent": {"confident": False},
            "generation_path": "resolve_error",
            "mode": mode,
        }

    intent, method = extract_intent_rules(question)
    engine = get_copilot_engine()
    if not intent.get("confident") and engine is not None and getattr(engine, "llm", None):
        try:
            intent, method = extract_intent_llm(engine, question)
        except Exception:
            pass

    if not intent.get("confident"):
        answer = (
            "I could not determine a clear intent from that question. "
            "Ask about a site (MCF/SAC/NRSC/Mauritius or stationN) and "
            "a class (congestion, tunnel, BGP, VRF, policy_drift) or path health."
        )
        return {
            "answer": answer,
            "intent": intent,
            "generation_path": f"refuse_no_intent:{method}",
            "mode": mode,
        }

    decls = load_declarations(decl_file) if decl_file else []
    fetched, status = fetch_model_values(decls, intent, feed_path=feed_path)
    if fetched is None:
        answer = format_final_answer(
            intent,
            {"host": intent.get("site"), "active_class": "unknown"},
            None,
            status="no_data",
        )
        return {
            "answer": answer,
            "intent": intent,
            "fetched": None,
            "generation_path": "no_data",
            "mode": mode,
            "status": status,
        }

    payload = assemble_payload(fetched, intent) if status == "ok" else None
    alert: dict[str, Any] | None = None
    generation_path = f"rules_{status}"
    if payload and engine is not None:
        try:
            alert = engine.generate(payload)
            generation_path = alert.get("generation_path") or "copilot_bridge"
        except Exception as exc:  # noqa: BLE001
            generation_path = f"generate_error:{exc}"
            alert = {
                "predicted_issue": payload.get("predicted_issue"),
                "confidence_score": payload.get("confidence_score"),
                "time_to_impact_minutes": payload.get("time_to_impact_minutes"),
                "root_cause": str(exc),
                "recommended_actions": [],
            }
    elif payload:
        alert = {
            "predicted_issue": payload.get("predicted_issue"),
            "confidence_score": payload.get("confidence_score"),
            "time_to_impact_minutes": payload.get("time_to_impact_minutes"),
            "root_cause": "CopilotEngine unavailable; raw model values only.",
            "recommended_actions": payload.get("recommended_actions") or [],
            "generation_path": "raw_payload",
        }
        generation_path = "raw_payload"

    answer = format_final_answer(intent, fetched, alert, status=status)
    try:
        import pipeline_feed

        pipeline_feed.log_copilot(
            f"retrieved: intent={intent.get('kind') if isinstance(intent, dict) else intent} "
            f"path={generation_path}"
        )
        if alert and alert.get("root_cause"):
            pipeline_feed.log_copilot(f"generated: {str(alert.get('root_cause'))[:160]}")
    except Exception:  # noqa: BLE001
        pass
    return {
        "answer": answer,
        "intent": intent,
        "alert": alert,
        "fetched": fetched,
        "generation_path": generation_path,
        "mode": mode,
        "status": status,
        "declarations_path": str(decl_file) if decl_file else None,
    }
