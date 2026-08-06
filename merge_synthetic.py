import shutil
from pathlib import Path

src_base = Path("predictive/data/deca/predictive/protocol/synth_gap_20260806T200701Z")
dst_base = Path("data/deca/predictive/protocol/synth_merged_20260806T200701Z")

# Ensure destination dirs exist
(dst_base / "L3_bgp_flap").mkdir(parents=True, exist_ok=True)
(dst_base / "L5_util_congestion").mkdir(parents=True, exist_ok=True)

# Copy L3
for item in (src_base / "L3_bgp_flap").iterdir():
    if item.is_dir():
        dst_item = dst_base / "L3_bgp_flap" / item.name
        if not dst_item.exists():
            shutil.copytree(item, dst_item)

# Copy L5
for item in (src_base / "L5_util_congestion").iterdir():
    if item.is_dir():
        dst_item = dst_base / "L5_util_congestion" / item.name
        if not dst_item.exists():
            shutil.copytree(item, dst_item)

print("Merge completed successfully.")
