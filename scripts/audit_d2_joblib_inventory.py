"""Compare all q2_severity.joblib bundles: n_features, split_mode, hyperparams."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(r"e:\deca-isro")
sys.path.insert(0, str(ROOT))
import joblib

warnings.filterwarnings("ignore")

rows = []
for p in ROOT.joinpath("data/deca/predictive/protocol_models").rglob("q2_severity.joblib"):
    try:
        b = joblib.load(p)
    except Exception as exc:
        rows.append({"path": str(p.relative_to(ROOT)), "error": f"{type(exc).__name__}: {exc}"})
        continue
    m = b.get("model")
    feat = b.get("feature_cols") or []
    rows.append(
        {
            "path": str(p.relative_to(ROOT)),
            "bytes": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "split_mode": b.get("split_mode"),
            "n_feat": len(feat),
            "has_bgp_rate_5s": any(str(c).startswith("bgp_rate_5s") for c in feat),
            "has_is_compound": "is_compound" in feat,
            "has_htb_ceil": any("htb_payload_ceil" in str(c) for c in feat),
            "max_depth": getattr(m, "max_depth", None),
            "n_estimators": getattr(m, "n_estimators", None),
            "reg_lambda": getattr(m, "reg_lambda", None),
            "min_child_weight": getattr(m, "min_child_weight", None),
            "learning_rate": getattr(m, "learning_rate", None),
            "raw_to_contig": b.get("raw_to_contig"),
        }
    )

print(json.dumps(rows, indent=2, default=str))
