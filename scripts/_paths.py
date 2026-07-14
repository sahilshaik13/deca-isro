"""Repo-rooted data paths — import from any script under scripts/."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PUBLIC_DIR = DATA_DIR / "raw" / "public"
PROCESSED_DIR = DATA_DIR / "processed"
RPI_NET_DIR = DATA_DIR / "rpi-net"
MODELS_DIR = REPO_ROOT / "models"
SCRIPTS_DIR = Path(__file__).resolve().parent

PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
RPI_NET_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
