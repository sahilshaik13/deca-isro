"""Environment-based settings for local dev and deployment."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from .env without extra dependencies."""
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    if raw.strip() == "*":
        return ["*"]
    return [part.strip() for part in raw.split(",") if part.strip()]


_load_dotenv()

# Server (uvicorn)
HOST = _env_str("DECA_HOST", "0.0.0.0")
PORT = _env_int("DECA_PORT", 8000)
RELOAD = _env_bool("DECA_RELOAD", False)

# Public URL clients use to reach this API (streamer, frontend, curl)
API_BASE_URL = _env_str("DECA_API_BASE_URL", f"http://localhost:{PORT}").rstrip("/")
PREDICT_URL = f"{API_BASE_URL}/api/v1/predict"

# CORS — comma-separated origins, or * for any
CORS_ORIGINS = _env_list("DECA_CORS_ORIGINS", ["*"])

# Paths (resolved to absolute for stable deploys)
MODELS_DIR = Path(_env_str("DECA_MODELS_DIR", str(BASE_DIR / "models"))).resolve()
CHROMA_DIR = Path(_env_str("DECA_CHROMA_DIR", str(BASE_DIR / "chroma_store"))).resolve()
RUNBOOKS_DIR = Path(_env_str("DECA_RUNBOOKS_DIR", str(BASE_DIR / "runbooks"))).resolve()
DATASET_PATH = Path(
    _env_str(
        "DECA_DATASET_PATH",
        str(BASE_DIR.parent / "data" / "processed" / "deca_unified_dataset.parquet"),
    )
).resolve()

# GGUF model files (LLM unset until a smaller alternative is chosen)
EMBED_MODEL_FILE = _env_str("DECA_EMBED_MODEL_FILE", "all-MiniLM-L6-v2-Q4_K_M.gguf")
LLM_MODEL_FILE = _env_str("DECA_LLM_MODEL_FILE", "")
EMBED_MODEL_REPO = _env_str(
    "DECA_EMBED_MODEL_REPO", "second-state/All-MiniLM-L6-v2-Embedding-GGUF"
)
LLM_MODEL_REPO = _env_str("DECA_LLM_MODEL_REPO", "")

# ML / LLM tuning
SEQ_LEN = _env_int("DECA_SEQ_LEN", 40)
LLM_N_CTX = _env_int("DECA_LLM_N_CTX", 2048)
LLM_N_THREADS = _env_int("DECA_LLM_N_THREADS", 6)
EMBED_N_CTX = _env_int("DECA_EMBED_N_CTX", 512)

# Demo streamer
STREAM_STEP_ROWS = _env_int("DECA_STREAM_STEP_ROWS", 5)
STREAM_INTERVAL_SEC = _env_int("DECA_STREAM_INTERVAL_SEC", 3)

# Prometheus / live RPi feed
PROMETHEUS_URL = _env_str("DECA_PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
PROMETHEUS_JOB = _env_str("DECA_PROMETHEUS_JOB", "deca_edge_nodes")
PROMETHEUS_JOBS = _env_list(
    "DECA_PROMETHEUS_JOBS",
    ["deca_edge_nodes", "deca_core_router", "deca_kafka_telemetry_bridge"],
)
# Physical edge interface(s) for throughput display.
# Use a PromQL regex to match mission data-plane NICs (iperf/MPLS path).
# eth0 only sees management traffic (~0 Mbps); lab traffic uses veth/vrf-mission.
THROUGHPUT_INTERFACE_REGEX = _env_str(
    "DECA_THROUGHPUT_INTERFACE_REGEX",
    "veth-pe-.*|vrf-mission|gre-te-.*",
)
# Deprecated single-interface override (used only if THROUGHPUT_INTERFACE_REGEX is empty)
EDGE_INTERFACE = _env_str("DECA_EDGE_INTERFACE", "")
RPI_STATIONS = _env_list(
    "DECA_RPI_STATIONS",
    ["station1", "station2", "station3"],
)
# When true, replace offline configured stations with hosts discovered in Prometheus
RPI_AUTO_DISCOVER = _env_bool("DECA_RPI_AUTO_DISCOVER", True)
TELEMETRY_HISTORY_LEN = _env_int("DECA_TELEMETRY_HISTORY_LEN", 60)
# PromQL rate() lookback — 1m reacts quickly on the dashboard; 5m is smoother but slow to ramp
PROMETHEUS_RATE_WINDOW = _env_str("DECA_PROMETHEUS_RATE_WINDOW", "1m")
# Instant-query gauges linger ~5m after scrape death; treat samples older than this as down.
PROM_STALE_SEC = _env_float("DECA_PROM_STALE_SEC", 15.0)
FEATURE_STEP_SECONDS = _env_int("DECA_FEATURE_STEP_SECONDS", 3)
FEATURE_WINDOW_MINUTES = _env_int("DECA_FEATURE_WINDOW_MINUTES", 10)

# Orchestrator (SQLite + controller gate + live operator ingest)
REPO_ROOT = BASE_DIR.parent
SQLITE_PATH = Path(
    _env_str(
        "DECA_ORCHESTRATOR_DB",
        str(REPO_ROOT / "data" / "deca" / "deca_orchestrator.db"),
    )
).resolve()
OPERATOR_ARCHIVE = Path(
    _env_str(
        "DECA_OPERATOR_ARCHIVE",
        str(REPO_ROOT / "data" / "rpi-net" / "archive" / "live"),
    )
).resolve()
OPERATOR_ACTIVE = Path(
    _env_str("DECA_OPERATOR_ACTIVE", str(REPO_ROOT / "data" / "rpi-net"))
).resolve()
SDWAN_CONTROLLER_URL = _env_str(
    "DECA_SDWAN_CONTROLLER_URL", "http://127.0.0.1:9280"
).rstrip("/")
# Skip eager GGUF/Chroma load so orchestrator endpoints come up fast.
# Dashboard /predict still available when heavy init succeeds or is forced on.
HEAVY_INIT = _env_bool("DECA_HEAVY_INIT", False)
COPILOT_SKIP_RAG = _env_bool("DECA_COPILOT_SKIP_RAG", True)

# ISRO site map — as-built single CORE on station3 (lo 10.1.3.1)
SITE_CATALOG = [
    {
        "id": "nrsc",
        "name": "NRSC Hyderabad",
        "role": "Branch CE on PE1 (Edge South)",
        "hosts": ["station1"],
        "mission_class": "payload",
    },
    {
        "id": "mauritius",
        "name": "Mauritius",
        "role": "Offshore CE on PE1 (~200 ms; lab alias → station1)",
        "hosts": ["station1"],
        "mission_class": "payload",
        "virtual": True,
    },
    {
        "id": "sac",
        "name": "SAC Ahmedabad",
        "role": "Datacenter CE on PE2 (Edge North/West)",
        "hosts": ["station2"],
        "mission_class": "ttc",
    },
    {
        "id": "mcf",
        "name": "MCF Hassan",
        "role": "Regional CE on PE2",
        "hosts": ["station2"],
        "mission_class": "ttc",
    },
    {
        "id": "core",
        "name": "CORE",
        "role": "P / BGP RR · single CORE on station3 (lo 10.1.3.1 · gre-te-pe1/pe2)",
        "hosts": ["station3"],
        "mission_class": "be",
    },
]

# GNS3 fleet strip — exporter host labels map to synthetic site hosts
SITE_CATALOG_GNS3 = [
    {
        "id": "nrsc",
        "name": "CE-NRSC",
        "role": "Gold branch CE on PE1",
        "hosts": ["gns3-pe1"],
        "mission_class": "ttc",
    },
    {
        "id": "mauritius",
        "name": "CE-Mauritius",
        "role": "Bronze rogue CE on PE1",
        "hosts": ["gns3-pe1"],
        "mission_class": "payload",
    },
    {
        "id": "sac",
        "name": "CE-SAC",
        "role": "Silver DC CE on PE2",
        "hosts": ["gns3-pe2"],
        "mission_class": "payload",
    },
    {
        "id": "mcf",
        "name": "CE-MCF",
        "role": "Bronze CE on PE2",
        "hosts": ["gns3-pe2"],
        "mission_class": "payload",
    },
    {
        "id": "core",
        "name": "CORE-N",
        "role": "Primary P · preserve DSCP",
        "hosts": ["gns3-core"],
        "mission_class": "be",
    },
    {
        "id": "core-s",
        "name": "CORE-S",
        "role": "Optional dual-P",
        "hosts": ["gns3-core"],
        "mission_class": "be",
        "virtual": True,
    },
    {
        "id": "shadnagar",
        "name": "CE-Shadnagar",
        "role": "Regional CE on PE1",
        "hosts": ["gns3-pe1"],
        "mission_class": "payload",
        "virtual": True,
    },
    {
        "id": "istrac",
        "name": "CE-ISTRAC",
        "role": "Regional CE on PE2",
        "hosts": ["gns3-pe2"],
        "mission_class": "payload",
        "virtual": True,
    },
    {
        "id": "hq",
        "name": "CE-ISRO-HQ",
        "role": "HQ CE on PE3",
        "hosts": ["gns3-pe3"],
        "mission_class": "payload",
        "virtual": True,
    },
    {
        "id": "bhopal",
        "name": "CE-Bhopal",
        "role": "Regional CE on PE3",
        "hosts": ["gns3-pe3"],
        "mission_class": "payload",
        "virtual": True,
    },
]


def site_catalog_for(fabric: str | None = None) -> list[dict]:
    fab = (fabric or "pi").strip().lower()
    return list(SITE_CATALOG_GNS3 if fab == "gns3" else SITE_CATALOG)
