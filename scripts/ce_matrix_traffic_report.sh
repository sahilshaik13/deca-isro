#!/usr/bin/env bash
# ce_matrix_traffic_report.sh — permute CE reachability + traffic, write a report.
#
# Exercises all four Customer Edges (NRSC, SAC, Mauritius, MCF) across:
#   S1  CE-loopback ping mesh (directed)
#   S2  Site-LAN workstation ping mesh (directed)
#   S3  iperf3 bulk (clear path) for gold / distant / regional / same-PE / reverse
#   S4  Gold path under mild gre-te-core netem, then clear
#
# Usage:
#   bash scripts/ce_matrix_traffic_report.sh
#   bash scripts/ce_matrix_traffic_report.sh --skip-netem
#   bash scripts/ce_matrix_traffic_report.sh --skip-iperf
#   DECA_MATRIX_OUT=/tmp/ce-report bash scripts/ce_matrix_traffic_report.sh
#
# Report: Markdown + JSON under data/deca/ce-matrix-reports/<timestamp>/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${DECA_MATRIX_OUT:-$ROOT/data/deca/ce-matrix-reports/$STAMP}"
SKIP_IPERF=0
SKIP_NETEM=0
PING_COUNT="${DECA_MATRIX_PING_COUNT:-3}"
IPERF_SEC="${DECA_MATRIX_IPERF_SEC:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-iperf) SKIP_IPERF=1; shift ;;
    --skip-netem) SKIP_NETEM=1; shift ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"
RESULTS_TSV="$OUT_DIR/results.tsv"
JSON_PATH="$OUT_DIR/report.json"
MD_PATH="$OUT_DIR/REPORT.md"
LOG_PATH="$OUT_DIR/run.log"
: >"$RESULTS_TSV"
: >"$LOG_PATH"

log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG_PATH"; }

ssh_sudo() {
  local host="$1"; shift
  # shellcheck disable=SC2029
  ssh -o ConnectTimeout=8 -o BatchMode=yes -T "$host" "sudo -n bash -c $(printf '%q' "$*")"
}

# site_id|human|host|ce_ns|ce_lo|ws_ns|ws_ip|srv_ns|srv_ip|role|rtt_hint_ms
SITE_ROWS=(
  "nrsc|NRSC Hyderabad|station1|ce-a|10.100.1.1|nrsc-ws|10.101.1.2|nrsc-srv|10.101.1.3|branch|5"
  "sac|SAC Ahmedabad|station2|ce-b|10.100.2.1|sac-ws|10.101.2.2|sac-srv|10.101.2.3|datacenter|5"
  "mauritius|Mauritius Distant|station1|ce-mauritius|10.100.3.1|mau-ws|10.101.3.2|mau-srv|10.101.3.3|distant|220"
  "mcf|MCF Hassan|station2|ce-mcf|10.100.4.1|mcf-ws|10.101.4.2|mcf-srv|10.101.4.3|regional|5"
)

site_field() {
  local id="$1" idx="$2" row
  for row in "${SITE_ROWS[@]}"; do
    IFS='|' read -r sid _ <<<"$row"
    if [[ "$sid" == "$id" ]]; then
      IFS='|' read -r -a a <<<"$row"
      printf '%s' "${a[$idx]}"
      return 0
    fi
  done
  return 1
}

record() {
  # situation|test|from|to|proto|ok|rtt_ms|loss_pct| thr_mbps|detail
  local situation="$1" test="$2" from="$3" to="$4" proto="$5"
  local ok="$6" rtt="${7:-}" loss="${8:-}" thr="${9:-}" detail="${10:-}"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$situation" "$test" "$from" "$to" "$proto" "$ok" "$rtt" "$loss" "$thr" "$detail" \
    >>"$RESULTS_TSV"
  if [[ "$ok" == "PASS" ]]; then
    log "PASS  [$situation] $test  $from → $to  rtt=${rtt:--} loss=${loss:--} thr=${thr:--}"
  else
    log "FAIL  [$situation] $test  $from → $to  ${detail:-}"
  fi
}

# --- ping from netns ---
do_ping() {
  local situation="$1" test="$2" host="$3" ns="$4" dest="$5" from_lbl="$6" to_lbl="$7" max_rtt="${8:-9999}" wait="${9:-2}"
  local out loss rtt ok="FAIL" detail=""
  out=$(ssh_sudo "$host" "ip netns exec $ns ping -n -c $PING_COUNT -W $wait $dest" 2>&1) || true
  loss=$(printf '%s\n' "$out" | grep -oE '[0-9]+% packet loss' | head -1 | tr -dc '0-9')
  loss=${loss:-100}
  rtt=$(printf '%s\n' "$out" | awk -F'/' '/rtt|round-trip/{print $5; exit}')
  rtt=${rtt:-}
  if [[ "$loss" -lt 100 ]]; then
    ok="PASS"
    if [[ -n "$rtt" ]] && awk -v r="$rtt" -v m="$max_rtt" 'BEGIN{exit !(r>m)}'; then
      ok="FAIL"
      detail="rtt ${rtt}ms exceeds expected max ${max_rtt}ms"
    fi
  else
    detail="100% loss or unreachable"
  fi
  # Distant sites: allow higher RTT — max_rtt already set high
  record "$situation" "$test" "$from_lbl" "$to_lbl" "icmp" "$ok" "${rtt:-}" "$loss" "" "$detail"
}

ensure_iperf_server() {
  local host="$1" ns="$2" port="$3"
  ssh_sudo "$host" "ip netns exec $ns bash -c 'ss -ltn | grep -q \":$port \" || iperf3 -s -D -p $port'"
}

do_iperf() {
  local situation="$1" test="$2"
  local chost="$3" cns="$4" dest="$5" port="$6"
  local shost="$7" sns="$8"
  local from_lbl="$9" to_lbl="${10}"
  local out thr ok="FAIL" detail=""

  ensure_iperf_server "$shost" "$sns" "$port" || true
  sleep 0.3
  out=$(ssh_sudo "$chost" \
    "ip netns exec $cns iperf3 -c $dest -p $port -t $IPERF_SEC -J" 2>&1) || true
  thr=$(printf '%s\n' "$out" | python3 -c '
import sys,json
raw=sys.stdin.read()
try:
  d=json.loads(raw)
  bps=d.get("end",{}).get("sum_sent",{}).get("bits_per_second") or d.get("end",{}).get("sum",{}).get("bits_per_second") or 0
  print(f"{bps/1e6:.2f}")
except Exception:
  print("")
' 2>/dev/null || true)
  if [[ -n "$thr" ]] && awk -v t="${thr:-0}" 'BEGIN{exit !(t>0.05)}'; then
    ok="PASS"
  else
    detail=$(printf '%s\n' "$out" | tr '\n' ' ' | head -c 180)
    [[ -z "$detail" ]] && detail="iperf3 failed / no throughput"
  fi
  record "$situation" "$test" "$from_lbl" "$to_lbl" "iperf3" "$ok" "" "" "${thr:-}" "$detail"
}

log "CE matrix start → $OUT_DIR"
log "ping_count=$PING_COUNT iperf_sec=$IPERF_SEC skip_iperf=$SKIP_IPERF skip_netem=$SKIP_NETEM"

# Preflight: netns present
log "=== Preflight: CE netns ==="
for row in "${SITE_ROWS[@]}"; do
  IFS='|' read -r sid human host ce_ns ce_lo ws_ns ws_ip srv_ns srv_ip role hint <<<"$row"
  if ssh_sudo "$host" "ip netns list | grep -qw $ce_ns"; then
    record "preflight" "netns_present" "$sid" "$host/$ce_ns" "check" "PASS" "" "" "" ""
  else
    record "preflight" "netns_present" "$sid" "$host/$ce_ns" "check" "FAIL" "" "" "" "missing netns"
  fi
done

# -------- S1: CE loopback directed mesh --------
log "=== S1: CE-loopback ping mesh ==="
SITES=(nrsc sac mauritius mcf)
for src in "${SITES[@]}"; do
  for dst in "${SITES[@]}"; do
    [[ "$src" == "$dst" ]] && continue
    sh=$(site_field "$src" 2); sns=$(site_field "$src" 3); slo=$(site_field "$src" 4)
    dlo=$(site_field "$dst" 4)
    hint=$(site_field "$dst" 10)
    # Mauritius involved → expect ~200ms; use looser cap when either end is distant
    max=80
    [[ "$src" == mauritius || "$dst" == mauritius ]] && max=400
    do_ping "S1_ce_lo_mesh" "ping_ce_lo" "$sh" "$sns" "$dlo" \
      "${src}:${slo}" "${dst}:${dlo}" "$max" 2
  done
done

# -------- S2: LAN workstation directed mesh --------
log "=== S2: Site-LAN ws ping mesh ==="
for src in "${SITES[@]}"; do
  for dst in "${SITES[@]}"; do
    [[ "$src" == "$dst" ]] && continue
    sh=$(site_field "$src" 2); wns=$(site_field "$src" 5)
    dip=$(site_field "$dst" 6)
    max=80
    [[ "$src" == mauritius || "$dst" == mauritius ]] && max=400
    do_ping "S2_lan_ws_mesh" "ping_lan_ws" "$sh" "$wns" "$dip" \
      "${src}-ws" "${dst}-ws:${dip}" "$max" 2
  done
done

# -------- S3: iperf clear --------
if [[ "$SKIP_IPERF" -eq 0 ]]; then
  log "=== S3: iperf3 clear-path combinations ==="
  # Gold: NRSC → SAC
  do_iperf "S3_iperf_clear" "gold_nrsc_to_sac" \
    station1 nrsc-ws 10.101.2.3 5201 station2 sac-srv \
    "nrsc-ws" "sac-srv:5201"
  # Distant: Mauritius → SAC
  do_iperf "S3_iperf_clear" "distant_mau_to_sac" \
    station1 mau-ws 10.101.2.3 5201 station2 sac-srv \
    "mau-ws" "sac-srv:5201"
  # Regional: MCF → NRSC
  do_iperf "S3_iperf_clear" "regional_mcf_to_nrsc" \
    station2 mcf-ws 10.101.1.3 5201 station1 nrsc-srv \
    "mcf-ws" "nrsc-srv:5201"
  # Reverse gold: SAC → NRSC
  do_iperf "S3_iperf_clear" "reverse_sac_to_nrsc" \
    station2 sac-ws 10.101.1.3 5201 station1 nrsc-srv \
    "sac-ws" "nrsc-srv:5201"
  # Same-PE PE1: NRSC → Mauritius
  do_iperf "S3_iperf_clear" "same_pe1_nrsc_to_mau" \
    station1 nrsc-ws 10.101.3.3 5201 station1 mau-srv \
    "nrsc-ws" "mau-srv:5201"
  # Same-PE PE2: SAC → MCF
  do_iperf "S3_iperf_clear" "same_pe2_sac_to_mcf" \
    station2 sac-ws 10.101.4.3 5201 station2 mcf-srv \
    "sac-ws" "mcf-srv:5201"
  # Cross: Mauritius → MCF
  do_iperf "S3_iperf_clear" "cross_mau_to_mcf" \
    station1 mau-ws 10.101.4.3 5201 station2 mcf-srv \
    "mau-ws" "mcf-srv:5201"
  # Cross: MCF → Mauritius
  do_iperf "S3_iperf_clear" "cross_mcf_to_mau" \
    station2 mcf-ws 10.101.3.3 5201 station1 mau-srv \
    "mcf-ws" "mau-srv:5201"
else
  log "Skipping S3 iperf (--skip-iperf)"
fi

# -------- S4: mild netem on gold path --------
if [[ "$SKIP_NETEM" -eq 0 && "$SKIP_IPERF" -eq 0 ]]; then
  log "=== S4: mild gre netem on station1, gold iperf + ping ==="
  ssh_sudo station1 "tc qdisc replace dev gre-te-core root netem delay 40ms 8ms distribution normal" || true
  sleep 2
  do_ping "S4_mild_netem" "ping_ce_lo_under_netem" station1 ce-a 10.100.2.1 \
    "nrsc:10.100.1.1" "sac:10.100.2.1" 120 2
  do_iperf "S4_mild_netem" "gold_nrsc_to_sac_under_netem" \
    station1 nrsc-ws 10.101.2.3 5201 station2 sac-srv \
    "nrsc-ws" "sac-srv:5201"
  log "Clearing netem on gre-te-core"
  ssh_sudo station1 "tc qdisc del dev gre-te-core root 2>/dev/null || true"
  sleep 1
  do_ping "S4_recover" "ping_ce_lo_after_clear" station1 ce-a 10.100.2.1 \
    "nrsc:10.100.1.1" "sac:10.100.2.1" 80 2
else
  log "Skipping S4 netem"
fi

# -------- Build JSON + Markdown report --------
python3 - "$RESULTS_TSV" "$JSON_PATH" "$MD_PATH" "$STAMP" "$OUT_DIR" <<'PY'
import csv, json, sys
from collections import defaultdict
from pathlib import Path

tsv, jpath, mdpath, stamp, out_dir = sys.argv[1:6]
rows = []
with open(tsv, newline="") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        p = line.split("\t")
        while len(p) < 10:
            p.append("")
        rows.append({
            "situation": p[0], "test": p[1], "from": p[2], "to": p[3],
            "proto": p[4], "ok": p[5], "rtt_ms": p[6], "loss_pct": p[7],
            "thr_mbps": p[8], "detail": p[9],
        })

passed = sum(1 for r in rows if r["ok"] == "PASS")
failed = sum(1 for r in rows if r["ok"] != "PASS")
by_sit = defaultdict(lambda: {"pass": 0, "fail": 0, "rows": []})
for r in rows:
    k = r["situation"]
    by_sit[k]["rows"].append(r)
    if r["ok"] == "PASS":
        by_sit[k]["pass"] += 1
    else:
        by_sit[k]["fail"] += 1

# Site health: did each site appear as from/to in a PASS ping?
sites = {"nrsc", "sac", "mauritius", "mcf"}
site_ok = {s: {"as_src_pass": 0, "as_dst_pass": 0, "as_src_fail": 0, "as_dst_fail": 0} for s in sites}
for r in rows:
    if r["proto"] not in ("icmp", "iperf3"):
        continue
    for s in sites:
        if r["from"].startswith(s):
            site_ok[s]["as_src_pass" if r["ok"] == "PASS" else "as_src_fail"] += 1
        if r["to"].startswith(s) or f"{s}:" in r["to"] or f"{s}-" in r["to"]:
            site_ok[s]["as_dst_pass" if r["ok"] == "PASS" else "as_dst_fail"] += 1

payload = {
    "stamp": stamp,
    "out_dir": out_dir,
    "summary": {"total": len(rows), "pass": passed, "fail": failed, "ok": failed == 0},
    "by_situation": {k: {"pass": v["pass"], "fail": v["fail"]} for k, v in by_sit.items()},
    "site_participation": site_ok,
    "failures": [r for r in rows if r["ok"] != "PASS"],
    "results": rows,
}
Path(jpath).write_text(json.dumps(payload, indent=2) + "\n")

lines = []
lines.append(f"# DECA CE Matrix Traffic Report — `{stamp}`")
lines.append("")
lines.append(f"**Overall:** {passed} PASS / {failed} FAIL / {len(rows)} total — "
             f"{'ALL GREEN' if failed == 0 else 'NEEDS ATTENTION'}")
lines.append("")
lines.append("## Situations")
lines.append("")
lines.append("| Situation | Pass | Fail |")
lines.append("| --- | ---: | ---: |")
for k in sorted(by_sit):
    v = by_sit[k]
    lines.append(f"| `{k}` | {v['pass']} | {v['fail']} |")
lines.append("")
lines.append("## Site participation (src/dst across icmp+iperf)")
lines.append("")
lines.append("| Site | src PASS | src FAIL | dst PASS | dst FAIL | Verdict |")
lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
for s in sorted(sites):
    v = site_ok[s]
    verdict = "OK" if v["as_src_fail"] == 0 and v["as_dst_fail"] == 0 and (v["as_src_pass"] + v["as_dst_pass"]) > 0 else "CHECK"
    if v["as_src_pass"] + v["as_dst_pass"] == 0:
        verdict = "NO DATA"
    lines.append(
        f"| **{s}** | {v['as_src_pass']} | {v['as_src_fail']} | {v['as_dst_pass']} | {v['as_dst_fail']} | {verdict} |"
    )
lines.append("")
if payload["failures"]:
    lines.append("## Failures")
    lines.append("")
    lines.append("| Situation | Test | From | To | Detail |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in payload["failures"]:
        det = (r["detail"] or "").replace("|", "/")[:120]
        lines.append(f"| `{r['situation']}` | {r['test']} | {r['from']} | {r['to']} | {det} |")
    lines.append("")
lines.append("## Full results")
lines.append("")
lines.append("| Sit | Test | From | To | Proto | OK | RTT ms | Loss % | Mbps |")
lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |")
for r in rows:
    lines.append(
        f"| `{r['situation']}` | {r['test']} | {r['from']} | {r['to']} | {r['proto']} | "
        f"**{r['ok']}** | {r['rtt_ms'] or '-'} | {r['loss_pct'] or '-'} | {r['thr_mbps'] or '-'} |"
    )
lines.append("")
lines.append(f"_Artifacts: `{out_dir}` (`REPORT.md`, `report.json`, `results.tsv`, `run.log`)_")
Path(mdpath).write_text("\n".join(lines) + "\n")
print(json.dumps(payload["summary"]))
PY

log "Report written: $MD_PATH"
log "JSON: $JSON_PATH"
echo
echo "=== CE MATRIX DONE ==="
echo "Report: $MD_PATH"
echo "Open:   cat $MD_PATH"
