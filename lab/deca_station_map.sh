#!/usr/bin/env bash
# deca_station_map.sh — terminal inventory of what belongs to each station.
# Usage:
#   stations              # via bash function / ~/deca_station_map.sh
#   bash lab/deca_station_map.sh
#   bash lab/deca_station_map.sh --live   # also probe systemd over SSH
set -uo pipefail

LIVE=0
[[ "${1:-}" == "--live" || "${1:-}" == "-l" ]] && LIVE=1

LAB_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${LAB_DIR}/.." && pwd)"

C_BOLD=$'\033[1m'
C_DIM=$'\033[2m'
C_CYAN=$'\033[36m'
C_GREEN=$'\033[32m'
C_YELLOW=$'\033[33m'
C_RED=$'\033[31m'
C_RESET=$'\033[0m'

hr() { printf '%s\n' "${C_DIM}────────────────────────────────────────────────────────────────────────${C_RESET}"; }
banner() {
  printf '\n%s╔══════════════════════════════════════════════════════════════════════╗%s\n' "$C_CYAN" "$C_RESET"
  printf '%s║%s  %-66s %s║%s\n' "$C_CYAN" "$C_BOLD" "$1" "$C_CYAN" "$C_RESET"
  printf '%s║%s  %-66s %s║%s\n' "$C_CYAN" "$C_DIM" "$2" "$C_CYAN" "$C_RESET"
  printf '%s╚══════════════════════════════════════════════════════════════════════╝%s\n' "$C_CYAN" "$C_RESET"
}

kv() { printf '  %-22s %s\n' "$1" "$2"; }
bullet() { printf '  • %s\n' "$1"; }
unit() { printf '  %-36s %s\n' "$1" "$2"; }

live_units() {
  local host="$1"
  shift
  local u state
  if ! ping -c1 -W1 "$host" &>/dev/null && ! ssh -q -o ConnectTimeout=3 -o BatchMode=yes "$host" true 2>/dev/null; then
    printf '  %s(live: host unreachable)%s\n' "$C_RED" "$C_RESET"
    return
  fi
  printf '  %s── live systemd ──%s\n' "$C_DIM" "$C_RESET"
  for u in "$@"; do
    state=$(ssh -q -o ConnectTimeout=4 -o BatchMode=yes "$host" \
      "systemctl is-active '$u' 2>/dev/null || echo missing" 2>/dev/null || echo unreachable)
    case "$state" in
      active|activating) printf '  %-36s %s%s%s\n' "$u" "$C_GREEN" "$state" "$C_RESET" ;;
      inactive|failed|missing) printf '  %-36s %s%s%s\n' "$u" "$C_YELLOW" "$state" "$C_RESET" ;;
      *) printf '  %-36s %s%s%s\n' "$u" "$C_RED" "$state" "$C_RESET" ;;
    esac
  done
}

printf '\n%sDECA-ISRO  ·  station ownership map%s\n' "$C_BOLD" "$C_RESET"
printf '%sRepo:%s %s\n' "$C_DIM" "$C_RESET" "$REPO"
printf '%sTip:%s  check stations  → live health   ·   stations --live  → units + SSH\n' "$C_DIM" "$C_RESET"
hr

# ---------------------------------------------------------------------------
# Overview strip
# ---------------------------------------------------------------------------
cat <<EOF
${C_BOLD}Lab LAN 192.168.50.0/24${C_RESET}

  brain (.1)     orchestrator — Prom / Kafka / controller / API / UI / ML
  station1 (.10) PE1 — NRSC + Mauritius
  station2 (.20) PE2 — SAC + MCF Hassan
  station3 (.30) CORE / P — backbone only (no CEs)

${C_DIM}Underlay: PE1 ──GRE/MPLS── CORE ──GRE/MPLS── PE2   (eth0 backup PE1↔PE2)
Overlay:  PE1 ══IPsec ESP══ PE2${C_RESET}
EOF

# ===========================================================================
# STATION 1
# ===========================================================================
banner "station1  ·  PE1" "192.168.50.10   RID 10.1.1.1   SSH: ssh station1"
hr
kv "Role" "Provider Edge PE1"
kv "Sites hosted" "NRSC (Branch) + Mauritius (Distant)"
kv "GRE" "gre-te-core 10.50.1.1/30 → CORE"
kv "Stack" "FRR · IPsec · VRF · HTB · Telegraf"

echo
printf '%s  Sites / namespaces%s\n' "$C_BOLD" "$C_RESET"
unit "NRSC ce-a" "attach 10.10.1.0/30  CE-lo 10.100.1.1  LAN 10.101.1.0/29"
unit "  nrsc-ws / nrsc-srv" ".2 / .3 on site LAN"
unit "Mauritius ce-mauritius" "attach 10.10.3.0/30  CE-lo 10.100.3.1  LAN 10.101.3.0/29"
unit "  mau-ws / mau-srv" ".2 / .3 + netem ~200ms RTT"

echo
printf '%s  systemd units (belong here)%s\n' "$C_BOLD" "$C_RESET"
unit "deca-ns.service" "create ce-a (NRSC)"
unit "deca-ns-mauritius.service" "distant CE + netem"
unit "deca-mauritius-bgp.service" "BGP AS 65013"
unit "deca-vrf-up.service" "vrf-mission / vrf-admin"
unit "deca-expansion-boot.service" "GRE · HTB · MPLS · site LANs · swanctl"
unit "frr.service" "OSPF · LDP · BGP VPNv4 · pathd SR-TE"
unit "strongswan-starter" "IPsec overlay to PE2"
unit "telegraf / chrony" "metrics :9273 · NTP"
unit "deca-watchdog.service" "+60s heal → /run/deca/station-ready"

echo
printf '%s  repo scripts that target this Pi%s\n' "$C_BOLD" "$C_RESET"
bullet "lab/deca-deploy.sh                 — writes CE-A ns + watchdog"
bullet "lab/deca_expand_phase_a.sh         — Mauritius CE + BGP"
bullet "lab/deca_expand_phase_g.sh         — NRSC/MAU site LANs"
bullet "lab/deca-expansion-boot.sh         — case station1: GRE/HTB/TE heal"
bullet "lab/swanctl/deca-sdwan.pe1.conf    — IPsec PE1 side"
bullet "lab/telemetry-pipeline/install_edge.sh station1"
bullet "scripts/inject_*.sh                — most faults SSH → station1"

[[ "$LIVE" -eq 1 ]] && live_units station1 \
  deca-ns.service deca-ns-mauritius.service deca-mauritius-bgp.service \
  deca-vrf-up.service deca-expansion-boot.service frr.service \
  strongswan-starter telegraf chrony deca-watchdog.service

# ===========================================================================
# STATION 2
# ===========================================================================
banner "station2  ·  PE2" "192.168.50.20   RID 10.1.2.1   SSH: ssh station2"
hr
kv "Role" "Provider Edge PE2"
kv "Sites hosted" "SAC Ahmedabad (DC) + MCF Hassan (Regional)"
kv "GRE" "gre-te-core 10.50.2.1/30 → CORE"
kv "Stack" "FRR · IPsec · VRF · HTB · Telegraf"

echo
printf '%s  Sites / namespaces%s\n' "$C_BOLD" "$C_RESET"
unit "SAC ce-b" "attach 10.10.2.0/30  CE-lo 10.100.2.1  LAN 10.101.2.0/29"
unit "  sac-ws / sac-srv" ".2 / .3  (+ iperf3 -s in ce-b)"
unit "MCF ce-mcf" "attach 10.10.4.0/30  CE-lo 10.100.4.1  LAN 10.101.4.0/29"
unit "  mcf-ws / mcf-srv" ".2 / .3"

echo
printf '%s  systemd units (belong here)%s\n' "$C_BOLD" "$C_RESET"
unit "deca-ns.service" "create ce-b (SAC) + iperf3 -s"
unit "deca-ns-mcf.service" "MCF regional CE"
unit "deca-vrf-up.service" "vrf-mission / vrf-admin"
unit "deca-expansion-boot.service" "GRE · HTB · MPLS · site LANs · swanctl"
unit "frr.service" "OSPF · LDP · BGP VPNv4 · pathd SR-TE"
unit "strongswan-starter" "IPsec overlay to PE1"
unit "telegraf / chrony" "metrics :9273 · NTP"
unit "deca-watchdog.service" "+60s heal → /run/deca/station-ready"

echo
printf '%s  repo scripts that target this Pi%s\n' "$C_BOLD" "$C_RESET"
bullet "lab/deca-deploy.sh                 — writes CE-B ns + watchdog"
bullet "lab/deca_expand_phase_g.sh         — MCF ns + SAC/MCF site LANs"
bullet "lab/deca-expansion-boot.sh         — case station2: GRE/HTB/TE heal"
bullet "lab/swanctl/deca-sdwan.pe2.conf    — IPsec PE2 side"
bullet "lab/telemetry-pipeline/install_edge.sh station2"

[[ "$LIVE" -eq 1 ]] && live_units station2 \
  deca-ns.service deca-ns-mcf.service deca-vrf-up.service \
  deca-expansion-boot.service frr.service strongswan-starter \
  telegraf chrony deca-watchdog.service

# ===========================================================================
# STATION 3
# ===========================================================================
banner "station3  ·  CORE / P" "192.168.50.30   RID 10.1.3.1   SSH: ssh station3"
hr
kv "Role" "Single CORE hub / P (BGP route-reflector)"
kv "Sites hosted" "none — no CE netns, no HTB, no IPsec"
kv "GRE" "gre-te-pe1 10.50.1.2/30 · gre-te-pe2 10.50.2.2/30"
kv "Stack" "FRR (OSPF · LDP · BGP RR · TE) · Telegraf"

echo
printf '%s  systemd units (belong here)%s\n' "$C_BOLD" "$C_RESET"
unit "deca-expansion-boot.service" "create GRE legs · enable MPLS/LDP/TE"
unit "frr.service" "transit + BGP RR for VPNv4"
unit "telegraf / chrony" "metrics :9273 · NTP"
unit "deca-watchdog.service" "heal FRR + Telegraf only"

echo
printf '%s  repo scripts that target this Pi%s\n' "$C_BOLD" "$C_RESET"
bullet "lab/deca-expansion-boot.sh         — case station3: GRE to PE1/PE2"
bullet "lab/deca_dual_core_*.sh            — design-only dual CORE (NOT applied)"
bullet "lab/telemetry-pipeline/install_edge.sh station3"

[[ "$LIVE" -eq 1 ]] && live_units station3 \
  deca-expansion-boot.service frr.service telegraf chrony deca-watchdog.service

# ===========================================================================
# BRAIN
# ===========================================================================
banner "brain  ·  orchestrator (not a Pi station)" "192.168.50.1   this laptop"
hr
kv "Role" "SSH ops · scrape · control · UI · ML"
echo
printf '%s  runs here (not on the Pis)%s\n' "$C_BOLD" "$C_RESET"
bullet "lab/deca_sdwan_controller.py       — AAR path select :9280"
bullet "deca-backend (FastAPI)             — orchestrator :8000"
bullet "deca-frontend (Next.js)            — dashboard :3000"
bullet "lab/telemetry-pipeline/            — Kafka · Prom :9090"
bullet "predictive/                        — Q1 LSTM / Q2 XGBoost campaigns"
bullet "lab/deca_diagnostic.sh             — check stations"
bullet "lab/deca_ops.sh                    — check / heal / install-boot"
bullet "lab/deca-deploy.sh                 — full plug-and-play restore"

hr
printf '\n%sDay-to-day commands%s\n' "$C_BOLD" "$C_RESET"
cat <<EOF
  stations                 this map (what belongs where)
  stations --live          same + live systemd on each Pi
  check stations           live health / reachability / VPN pings
  bash lab/deca_ops.sh check
  bash lab/deca-deploy.sh  full restore when needed
  ssh station1|station2|station3

${C_DIM}Docs: docs/STATION_NETWORK_SETUP.md  ·  lab/README.md${C_RESET}
EOF
printf '\n'
