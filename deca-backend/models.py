"""Offline model fetch — DISABLED by default for air-gap demos.

Set DECA_ALLOW_HF_DOWNLOAD=1 to permit an explicit one-shot HuggingFace fetch.
Prefer copying GGUFs onto disk instead.
"""
from __future__ import annotations

import os
import sys

import config


def download_deca_models() -> None:
    allow = os.environ.get("DECA_ALLOW_HF_DOWNLOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not allow:
        print(
            "Refusing HuggingFace download (air-gap). "
            "Place GGUFs under "
            f"{config.MODELS_DIR} or re-run with DECA_ALLOW_HF_DOWNLOAD=1.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    from huggingface_hub import hf_hub_download

    os.makedirs(config.MODELS_DIR, exist_ok=True)
    print(f"Starting downloads to '{config.MODELS_DIR}' directory...\n")

    if not config.LLM_MODEL_FILE or not config.LLM_MODEL_REPO:
        print(
            "Skipping LLM download (set DECA_LLM_MODEL_FILE + DECA_LLM_MODEL_REPO).\n",
            file=sys.stderr,
        )
    else:
        print(f"Downloading LLM GGUF ({config.LLM_MODEL_FILE})...")
        hf_hub_download(
            repo_id=config.LLM_MODEL_REPO,
            filename=config.LLM_MODEL_FILE,
            local_dir=str(config.MODELS_DIR),
            local_dir_use_symlinks=False,
        )
        print("LLM downloaded successfully.\n")

    print("Downloading all-MiniLM-L6-v2 (RAG Embedding)...")
    hf_hub_download(
        repo_id=config.EMBED_MODEL_REPO,
        filename=config.EMBED_MODEL_FILE,
        local_dir=str(config.MODELS_DIR),
        local_dir_use_symlinks=False,
    )
    print("MiniLM downloaded successfully.\n")
    print("Setup complete. Offline AI models are ready.")


if __name__ == "__main__":
    download_deca_models()
