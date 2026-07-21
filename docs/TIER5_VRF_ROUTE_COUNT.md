# Tier 5 — `vrf_route_count` on station2

Phase 3 of the ROI roadmap. Orthogonal protocol-level features that a tunnel/congestion fault on PE1 cannot physically drown.

**Prerequisite (met):** multi-label sigmoid falsification on compound overlap legs — **0/25** drowned-target windows pass (`scripts/deca_multilabel_falsification.py`, `models/multilabel_falsification_report.json`). Architecture-only fix is rejected; protocol features are justified.

**Primary blind spot:** `tunnel_degradation` + `vrf_leakage` compound — VRF is injected on PE2 (`station2`) but shared eth0 dynamics echo PE1 tunnel symptoms and wash out the 20 rolling traffic features.

**Status: pipeline + lab wiring done, injector bug fixed, corrected leak verified live end-to-end (§0). Campaign / retrain / blind re-grade next.**

---

## 0. Finding: `inject_vrf_leakage()` has targeted a phantom VRF since day one

While wiring the exporter, `show ip route vrf ADMIN summary` returned `% VRF ADMIN not found` on both PEs. `show vrf` confirms the real deployed VRF is named **`vrf-admin`** (id 5, table 200), not `ADMIN`:

```text
$ sudo vtysh -c "show vrf"
vrf vrf-admin id 5 table 200 (configured)
vrf vrf-mission id 4 table 100 (configured)
```

`scripts/deca_fault_campaign.py` (`inject_vrf_leakage`, and its `clear_all_faults` counterpart) has always run:

```text
router bgp 65001 vrf ADMIN
 address-family ipv4 unicast
  rt vpn import 65001:100
```

FRR happily creates a **detached** `bgp vrf ADMIN` instance for a name zebra has no VRF for — it accepted the config but the RT import never bound to the real `vrf-admin` route table. Evidence on station2's running-config (leftover from prior campaign runs, never cleaned because `clear_all_faults` targets the same wrong name):

```text
router bgp 65001 vrf ADMIN
exit
!
```

**Implication:** every historical `vrf_leakage` fault run in the lake was, at the control-plane level, a **no-op** — no real route leaked into any VRF table. The class's telemetry shape came entirely from the accompanying synthetic PE2 `netem` ramp (`tc qdisc replace ... delay ... loss ...`), i.e. the "circumstance" symptoms code comments call necessary because "pure RT-wait left almost no telemetry shape." That comment was correct, but for the wrong reason assumed at the time — it wasn't that a real leak is subtle, it's that **no real leak was happening**.

This does **not** invalidate the compound-overlap falsification conclusion (§ prerequisite) — that result only depended on traffic features being drowned, which holds regardless of what caused the VRF-labelled window.

**Fixed 2026-07-20** (user-approved): `inject_vrf_leakage()` / `clear_all_faults()` now target `router bgp 65001 vrf vrf-admin` (was `vrf ADMIN`). The stray orphaned `vrf ADMIN` bgp instance was removed from station2 via a one-off (`scripts/deca_vrf_cleanup_admin_stub.py`).

**Verified live:** running the corrected injector command manually pulled 4 mission-VPN prefixes (6 paths) into `vrf-admin`'s **BGP table** (`show bgp vrf vrf-admin ipv4 unicast`: `0 → 4` routes). `clear_all_faults()` reverted it back to `0`. **However the RIB never installs these routes** (`show ip route vrf vrf-admin summary` stayed `0` throughout) — the imported VPNv4 prefixes' next hops don't resolve across the VRF boundary in this lab topology. The exporter (§2.1) therefore counts the **BGP table**, not the RIB, which is the real and reliable fault fingerprint.

---

## 1. Metric definition

| Field | Value |
| --- | --- |
| **Canonical name (internal)** | `vrf_route_count` |
| **Real Prometheus series** | `vrf_route_count_value` (Telegraf suffixes the `inputs.exec` field name `value` onto `name_override` — confirmed live, see §2.2) |
| **Host (phase 1)** | `station2` (PE2 — VRF leak injector) |
| **Source** | FRR `vtysh` **BGP table** per VRF (`show bgp vrf <vrf> ipv4 unicast`) — **not** the RIB, see §0 |
| **Cadence** | 5 s (Telegraf `inputs.exec` interval = Prometheus `scrape_interval`) |
| **Type** | Gauge (instantaneous BGP table prefix count) |

### VRF tables emitted

| `vrf` label | Real FRR name | Role |
| --- | --- | --- |
| `vrf-admin` | `vrf-admin` (id 5, table 200) | **Leak fingerprint** — wrong RT import (`65001:100`) pulls mission VPN prefixes into this BGP table |
| `vrf-mission` | `vrf-mission` (id 4, table 100) | Control — CE/VPN dataplane table; should stay stable during leak |

Confirmed baseline (both PEs, before any leak, live 2026-07-20):

```text
vrf_route_count_value{host="station1",vrf="vrf-admin"}   0
vrf_route_count_value{host="station1",vrf="vrf-mission"} 4
vrf_route_count_value{host="station2",vrf="vrf-admin"}   0
vrf_route_count_value{host="station2",vrf="vrf-mission"} 4
```

`vrf-admin` sitting at exactly `0` on both PEs (pre-fix) is itself evidence for §0 — no real leak had ever populated it.

Confirmed shape with the fixed injector (manual test, then reverted):

| Phase | `vrf_route_count_value{vrf="vrf-admin"}` (station2) | Traffic features on eth0 |
| --- | --- | --- |
| Healthy | `0` (confirmed) | Calm |
| `vrf_leakage` (corrected injector) | **`0 → 4`** within ~2s of the `rt vpn import` command (confirmed) | Mild PE2 netem ramp |
| Revert (`clear_all_faults`) | **`4 → 0`** (confirmed) | Reverts |
| `tunnel` + `vrf_leakage` compound | Same `0 → 4` step | Loud tunnel echo (drowns traffic features, not this one) |

The model gets **8 new engineered columns** per raw metric (long 10 min + short 2 min × slope / rolling_std / rolling_mean / accel) — same `engineer_features()` path as `ifInOctets`, etc.

---

## 2. Collector — FRR → Telegraf (deployed + verified live)

### 2.1 Shell exporter (`/usr/local/bin/deca-vrf-route-count.sh`)

Deployed on **station1** and **station2** via `lab/deca-deploy.sh`; source at [`lab/deca-vrf-route-count.sh`](../lab/deca-vrf-route-count.sh).

```bash
#!/usr/bin/env bash
set -euo pipefail

count_routes() {
  local vrf="$1"
  # BGP table, not RIB/FIB: a leaked VPNv4 import shows up in the BGP table
  # immediately, but its next hop never resolves across the VRF boundary in
  # this lab topology, so it's never installed into the RIB (verified
  # 2026-07-20 -- `show ip route vrf vrf-admin summary` stayed 0 through a
  # live, confirmed leak). Footer line is "Displayed N routes and M total
  # paths" (or "No BGP prefixes displayed, 0 exist" when empty).
  sudo vtysh -c "show bgp vrf ${vrf} ipv4 unicast" 2>/dev/null \
    | awk '/^Displayed/ { print $2; exit } /^No BGP prefixes/ { print 0; exit }'
}

emit() {
  local vrf="$1" val
  val="$(count_routes "${vrf}")"
  val="${val:-0}"
  printf 'vrf_route_count,vrf=%s value=%s\n' "${vrf}" "${val}"
}

emit vrf-admin
emit vrf-mission
```

**Permission note:** Telegraf's `inputs.exec` runs as the unprivileged **`_telegraf`** service user (Debian/Ubuntu underscore convention — confirmed via `systemctl show telegraf -p User`; do not assume `telegraf`). The FRR vty socket is root/`frrvty`-only, so a sudoers NOPASSWD drop-in is required and deployed:

```text
# /etc/sudoers.d/90-telegraf-vtysh (0440, validated with visudo -cf)
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show bgp vrf vrf-admin ipv4 unicast, /usr/bin/vtysh -c show bgp vrf vrf-mission ipv4 unicast
```

### 2.2 Telegraf fragment (`/etc/telegraf/telegraf.d/deca-vrf-route-count.conf`) — deployed

```toml
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-vrf-route-count.sh"]
  timeout = "4s"
  interval = "5s"
  data_format = "influx"
  name_override = "vrf_route_count"
```

Verified live on both PEs after `systemctl restart telegraf`:

```text
$ curl -s localhost:9273/metrics | grep vrf_route_count
# HELP vrf_route_count_value Telegraf collected metric
# TYPE vrf_route_count_value untyped
vrf_route_count_value{host="station2",vrf="vrf-admin"} 0
vrf_route_count_value{host="station2",vrf="vrf-mission"} 4
```

### 2.3 Automated deploy

```bash
bash lab/deca-deploy.sh
# → "Writing deca-vrf-route-count exporter + Telegraf fragment (station1/2)"
# → "Verifying vrf_route_count_value on Telegraf :9273 (station1/2)"
```

Idempotent; safe to re-run. Installs the sudoers drop-in, exporter script, Telegraf `.conf` fragment, restarts `telegraf`, and greps `:9273/metrics` for `vrf_route_count_value` on both PEs.

---

## 3. Prometheus scrape (verified end-to-end)

No job change — existing `deca_edge_nodes` targets already scrape `:9273`:

```yaml
# /etc/prometheus/prometheus.yml (laptop)
scrape_configs:
  - job_name: "deca_edge_nodes"
    static_configs:
      - targets: ["192.168.50.10:9273", "192.168.50.20:9273"]
```

Confirmed live via the laptop's own Prometheus:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=vrf_route_count_value' \
  | jq '.data.result[] | {host: .metric.host, vrf: .metric.vrf, value: .value[1]}'
```

```json
{"host": "station1", "vrf": "vrf-admin",   "value": "0"}
{"host": "station1", "vrf": "vrf-mission", "value": "4"}
{"host": "station2", "vrf": "vrf-admin",   "value": "0"}
{"host": "station2", "vrf": "vrf-mission", "value": "4"}
```

---

## 4. PromQL — live operator & campaign export (wired)

Added identically to `PROM_QUERIES` in `scripts/deca_live_common.py` and the mirrored `queries` dict in `deca_fault_campaign.py`'s Prometheus export block:

```python
"vrf_route_count": 'max by (host) (vrf_route_count_value{vrf="vrf-admin"})',
```

Optional second channel (later, for BGP-under-VRF flip on station1):

```python
"bgp_hold_timer_remaining": (
    'min by (host) (bgp_peer_hold_timer_seconds{peer=~".*"})'
),
```

### Range query parameters (unchanged)

| Param | Value |
| --- | --- |
| URL | `http://localhost:9090/api/v1/query_range` |
| `step` | `15` (seconds) — matches `engineer_features(step_seconds=15)` |
| Window | blind run `[start, end]` or campaign `[_campaign_start, now]` |

Unlike `bgp_update_rate`, **no CSV stamping** — this is a real scrape series end-to-end.

---

## 5. Training pipeline wiring (done)

### 5.1 `METRIC_MAP` (`scripts/rebuild_unified.py`)

```python
METRIC_MAP = {
    # ...
    "vrf_route_count": "vrf_route_count",  # Tier 5 — FRR vrf-admin route count
}
```

### 5.2 Telemetry allow-list (`_clean_telemetry`)

```python
tele = tele[tele["metric"].isin({
    "ifInOctets", "ifOutOctets", "jitter_ms", "packet_loss_pct",
    "bgp_update_rate", "vrf_route_count",  # Tier 5
})]
```

### 5.3 Feature engineering

No code change — `engineer_features()` groups by `metric` and emits:

- `vrf_route_count_slope`, `_rolling_std`, `_rolling_mean`, `_accel`
- `vrf_route_count_w2m_*` (2 min scale)

A real leak onset produces a **positive `vrf-admin` slope / accel** even when `jitter_ms` / `packet_loss_pct` on station2 are dominated by PE1 tunnel netem — confirmed with the fixed injector (§0: `0 → 4` on leak, `4 → 0` on revert).

### 5.4 Historical lake gap

Pre-Tier-5 campaign exports lack `vrf_route_count`. Median impute fills missing columns on old rows (existing notebook behaviour). Next:

1. Run a fresh `vrf_leakage` + compound overlap campaign against the corrected injector (§0 fix applied, verified live).
2. Rebuild → retrain — promote gate unchanged (**macro-F1 ≥ 0.717** on school exam).

---

## 6. Live operator path

```
Prometheus query_range (PROM_QUERIES)
        ↓
fetch_telemetry_long()          # deca_live_common.py
        ↓
_clean_telemetry + engineer_features()   # rebuild_unified.py (identical to train)
        ↓
per-host wide frame (station2 gets vrf_route_count_* columns)
        ↓
classifier + VRF origin-lock on station2 only   # deca_live_operator.py
```

VRF origin-lock (already shipped) stays: only `station2` may confirm `vrf_leakage`. Tier 5 gives the model a **station2-local** feature that does not require disambiguating drowned eth0 statistics — once the injector actually produces one.

---

## 7. Validation plan

### 7.1 Smoke (metric alive) — done

| Step | Result |
| --- | --- |
| Telegraf metrics on station1 + station2 | `vrf_route_count_value` present, both `vrf` labels |
| Prom targets | `2/2` edge nodes exposing the series |
| Baseline `vrf-admin` count | `0` on both PEs |
| Baseline `vrf-mission` count | `4` on both PEs (stable control) |

### 7.2 Leak reproduction — done

Manual test with the corrected injector command: `vrf-admin` went `0 → 4` within ~2s of the `rt vpn import 65001:100` command under `router bgp 65001 vrf vrf-admin`; `clear_all_faults()` reverted it `4 → 0`. Confirmed on the BGP table (`show bgp vrf vrf-admin ipv4 unicast`); RIB never installs these routes in this topology (§0), so the exporter deliberately reads the BGP table.

### 7.3 Isolated blind (regression)

Re-run isolated `vrf_leakage` blind with gates on after the injector fix — expect **2/2** (was passing on traffic+stamped BGP; should not regress, and should now also be grounded in a real signal).

### 7.4 Compound blind (primary)

Re-grade `tunnel_degradation` + `vrf_leakage` overlap (wave-2 schedule):

| Leg | Prior result | Tier-5 pass criterion |
| --- | --- | --- |
| Tunnel on station1 | HIT | Still HIT (traffic features) |
| VRF on station2 | MISS (drowned) | **HIT** — `vrf_route_count_*` crosses confirm threshold with origin-lock |

Scoring: existing `deca_blind_scorecard.py` + compound rollup in `data/rpi-net/blind-tests/CUMULATIVE.md`.

### 7.5 Promote gate

```bash
python scripts/rebuild_unified.py
# retrain notebook / orchestrator
# candidate macro-F1 must beat 0.717 without isolated VRF regression
```

---

## 8. Phase 2 (after vrf_route_count promotes)

| Feature | Host | PromQL source | Compound target |
| --- | --- | --- | --- |
| `bgp_hold_timer_remaining` | station1 | FRR BGP peer SNMP or `vtysh` exec | BGP drowned under `bgp+VRF` flip |
| Tunnel SA / rekey duration | station1/2 | StrongSwan / `swanctl` exec | Tunnel class under overlap |

Track in `docs/DECA_ROI_TIERS.md` § Tier 5.

---

## 9. File checklist

| Artifact | Status |
| --- | --- |
| `lab/deca-vrf-route-count.sh` | Added, targets real `vrf-admin`, counts BGP table |
| `/etc/sudoers.d/90-telegraf-vtysh` (both PEs) | Deployed, `_telegraf` user, BGP-table command |
| Pi `telegraf.d/deca-vrf-route-count.conf` (both PEs) | Deployed via `lab/deca-deploy.sh`, telegraf restarted |
| `scripts/deca_live_common.py` | `PROM_QUERIES["vrf_route_count"]` wired |
| `scripts/deca_fault_campaign.py` | Export query mirrored; `inject_vrf_leakage`/`clear_all_faults` **fixed** to target `vrf-admin` |
| `scripts/deca_vrf_cleanup_admin_stub.py` | One-off: removed stray phantom `vrf ADMIN` bgp instance from station2 |
| `scripts/rebuild_unified.py` | `METRIC_MAP` + allow-list wired |
| `docs/DECA_ROI_TIERS.md` | Linked here, status "in progress" |
| **Next** | Run `vrf_leakage` + compound overlap campaign, rebuild, retrain, blind re-grade |
