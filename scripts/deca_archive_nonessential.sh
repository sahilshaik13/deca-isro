#!/usr/bin/env bash
# Archive non-essential lab/experiment clutter. Keeps lake-building campaign
# runs, the promoted model, and the Tier-5c / foundational blind scoreboard.
set -euo pipefail
cd /home/brain/deca-isro

ARCH_BT=data/rpi-net/archive/blind-tests
ARCH_LIVE=data/rpi-net/archive/live
ARCH_LOGS=data/rpi-net/archive/runs_logs
ARCH_EXP=models/archive/experiments
ARCH_PROC=data/processed/archive
mkdir -p "$ARCH_BT" "$ARCH_LIVE" "$ARCH_LOGS" "$ARCH_EXP" "$ARCH_PROC"

move_git() {
  # Prefer git mv when tracked; else plain mv.
  local src="$1" dest="$2"
  if [[ ! -e "$src" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if git ls-files --error-unmatch "$src" >/dev/null 2>&1 || \
     git ls-files --error-unmatch "$src"/* >/dev/null 2>&1; then
    git mv "$src" "$dest" 2>/dev/null || mv "$src" "$dest"
  else
    mv "$src" "$dest"
  fi
  echo "  archived: $src -> $dest"
}

echo "=== Archive intermediate blind-tests (keep Tier-5c scoreboard + foundational) ==="
# KEEP (do not list): 
#   CUMULATIVE.md README.md aggregate_*.json compound_series_*rollup*
#   control_baseline_feature_20260721_2241_20m
#   blind_baseline_feature_{tunnel,bgp}_*
#   blind_vrf_isolated_20260719_1333_45m
#   blind_echo_20260719_1102_45m control_echo_20260719_1027_30m
#   blind_20260718_0848_60m blind_20260718_2219_60m control_20260718_0848_60m
#   specificity_exam_v1_20260718_2107 specificity_exam_v2_20260718_2142
#   blind_compound_{bgp_route_flap,congestion_breach,tunnel_degradation}_20260719_*  (first series)

BLIND_ARCHIVE=(
  blind_20260716_1537_60m
  blind_20260716_1924_60m
  control_20260716_1924_60m
  control_fp_check2_20260717_30m
  control_after_vrf_20260718_2142
  blind_vrfcheck_20260719_0210_45m
  specificity_exam_v1_20260717_1022
  specificity_exam_v1_20260718_0848
  specificity_exam_v2_20260718_1752
  control_post_overlap_20260719_1952_20m
  control_post_overlap_20260720_0133_20m
  control_post_overlap_20260720_2346_20m
  control_post_overlap_20260721_1409_20m
  control_post_overlap_20260721_1951_20m
  blind_compound_tunnel_recheck_20260719_2012_40m
  blind_compound_tunnel_recheck_20260720_0154_40m
  blind_compound_tunnel_recheck_20260721_0007_40m
  blind_compound_tunnel_recheck_20260721_1430_40m
  blind_compound_tunnel_recheck_20260721_2012_40m
  blind_compound_bgp_recheck_20260719_1516_40m
  blind_compound_bgp_recheck_20260720_0213_40m
  blind_compound_bgp_recheck_20260721_0023_40m
  blind_compound_bgp_recheck_20260721_1446_40m
  blind_compound_bgp_recheck_20260721_2029_40m
)

for d in "${BLIND_ARCHIVE[@]}"; do
  move_git "data/rpi-net/blind-tests/$d" "$ARCH_BT/$d"
done

echo "=== Archive duplicate live/ copies of archived blinds ==="
for d in "${BLIND_ARCHIVE[@]}"; do
  if [[ -d "data/rpi-net/live/$d" ]]; then
    move_git "data/rpi-net/live/$d" "$ARCH_LIVE/$d"
  fi
done

echo "=== Archive run wrapper logs only (keep campaign dirs for rebuild) ==="
for f in \
  data/rpi-net/runs/compound_overlap_pipeline.log \
  data/rpi-net/runs/compound_overlap_pipeline_nohup.log \
  data/rpi-net/runs/compound_overlap_w2_nohup.log \
  data/rpi-net/runs/20260715_191519_circ_v2_nohup.out \
  data/rpi-net/runs/spec_data_20260717_2352_orchestrator.log
do
  [[ -e "$f" ]] && move_git "$f" "$ARCH_LOGS/$(basename "$f")"
done

echo "=== Archive processed bak + portability dry-run samples ==="
for f in \
  data/processed/deca_unified_dataset.parquet.bak_pre_rebuild \
  data/processed/deca_unified_raw.parquet.bak_pre_rebuild \
  data/processed/network_a_control_sample.parquet \
  data/processed/network_b_scale10x_sample.parquet
do
  [[ -e "$f" ]] && mv "$f" "$ARCH_PROC/$(basename "$f")" && echo "  archived: $f"
done

echo "=== Archive bulky experiment trees (FINDINGS stay reachable under models/archive) ==="
for d in compound_drowning_fix compound_fix_round_2 compound_fix_round_3 tier_b_mixed tier_b_scale10x; do
  if [[ -e "models/experiments/$d" ]]; then
    mv "models/experiments/$d" "$ARCH_EXP/$d"
    echo "  archived: models/experiments/$d"
  fi
done
[[ -e models/experiments/tier_b_scale10x_comparison.json ]] && \
  mv models/experiments/tier_b_scale10x_comparison.json "$ARCH_EXP/" && \
  echo "  archived: tier_b_scale10x_comparison.json"

echo "=== Done ==="
echo "Active blind-tests:"; ls data/rpi-net/blind-tests | head -40
echo "Active experiments:"; ls models/experiments 2>/dev/null || true
echo "Archive roots:"; du -sh data/rpi-net/archive models/archive data/processed/archive 2>/dev/null
