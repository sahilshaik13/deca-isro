# Capture contract (Lane A) — frozen before long campaign

**Status:** LOCKED 2026-08-05  
**Purpose:** Fix metric physics *before* any 12.5 h campaign. Smoke-validate, then freeze. Do not retrain Q1/Q2 for promote on the old patched matrix expecting miracles.

**Does not touch locked cite board:** holdout **0.884** · chaos_final **0.815** · GNS3 transfer **0.655** (Pi `d2`) · Q2 root **0.992** · Q1 loss **7.1s** · jitter **27.2**. (GNS3 twin route `d3` **0.722** is per-fabric only — not a substitute for the 0.655 cite.)

---

## Locked choices (implementation decisions)

### Asymmetry — B + C + D

| Rule | Detail |
| --- | --- |
| **Canonical** | `path_asymmetry` = \|`latency_gre_ms` − `latency_eth0_ms`\| at the **same 1 Hz edge probe** |
| **Emit** | `sdwan_tunnel_stats.sh` (already computes it); Prom scrape **edge / kafka bridge** only |
| **Capture** | Always overwrite from gre/eth0 at write time (never trust a 5 s controller hold) |
| **Q2** | **Drop** raw `path_asymmetry` from `FEATURE_COLS`. Keep only derived `path_asymmetry_ms_*` from latency in the window |
| **Forbidden** | Scraping `path_asymmetry{job="deca_sdwan_controller"}` into train CSVs |

### Util — post-HTB PE egress (not `ce_util`)

| Rule | Detail |
| --- | --- |
| **Canonical training column** | `util_gre_mbps` (name kept for schema compatibility) |
| **Meaning** | **Tx byte-rate (Mbps) on PE `eth0`** — the iface that carries PS13 HTB root on Pi |
| **Cadence** | Edge @ **1 Hz** (tunnel_stats / Telegraf), not controller `POLL_SECONDS=5` |
| **PromQL** | `sdwan_path_util_mbps{…,path="eth0"}` — **single path**, never `max(gre\|eth0)` |
| **Approach target** | **Configured payload ceil** on the class that actually shapes CE util traffic (see L5 inject below). Soft payload ≈ **34 Mbit** on 40 Mbit WAN parent. |
| **Not canonical for ceiling** | `ce_util_mbps` (CE-SLA only) · GRE util alone · controller iface snapshot · **changing PE `1:15` alone** (encapped CE flows miss it → BE `1:20`) |
| **GNS3** | Same contract after twin emits eth0 (or documented underlay egress) util @1 Hz |

### Util Q1 labeling — schedule-gated (anti-confound)

**Smoke proof (`contract_smoke_l5_tcramp_*`):** during early tc-ramp steps, class ceil was **5–18 Mbit** while eth0 TX already sat **~22–27 Mbps** (other classes / default on the same iface). **8/16** early steps would look “already near payload ceil” if labels used raw eth0 alone → util LSTM would learn a false early breach.

| Rule | Detail |
| --- | --- |
| **Schedule sidecar** | L5 inject writes `util_ceil_schedule.jsonl`: `{ts_unix, htb_payload_ceil_mbps, phase}` each step + plateau |
| **Feature** | Still `util_gre_mbps` (eth0 TX) in the window |
| **Breach (ETA target)** | First time **`htb_payload_ceil_mbps ≥ end_mbit`** (scheduled payload ceil hit), *not* first time eth0 crosses a Mbps threshold |
| **Usable windows** | Only while **`htb_payload_ceil_mbps ≥ 0.70 × end_mbit`** (late ramp + plateau). Earlier windows: `label_usable=false` for util head |
| **Forbidden** | Training util TTI on eth0≥thr when scheduled ceil is still low |

Plateau residency remains the physical check that eth0 *can* sit near payload ceil when the class is actually there; labels must not credit eth0 for that before the class schedule says so.

### Gaps — A + B + C together

| Rule | Detail |
| --- | --- |
| **A** | Window builders **require** 1 Hz alignment (`align_1hz`) before ETA/features — default on, not opt-in |
| **B** | Q1 ETA from **timestamps**: `breach_ts − end_ts` (seconds), not `breach_idx − end_idx` |
| **C** | `capture_live` logs gap events; optional one Prom retry when `ts` would skip |

### L2 CPU — user plateau

| Rule | Detail |
| --- | --- |
| **Primary signal** | `cpu_usage_user` sustained elevated plateau for inject duration |
| **Forbidden** | Training / demoting on `cpu_usage_system` alone |
| **Smoke** | user max ≥35 · residency(≥25%) ≥20 s |

### L3 BGP — flap rate

| Rule | Detail |
| --- | --- |
| **Primary signal** | `bgp_flap_count` counter Δ over soft-clear cycles (not link-down by default) |
| **Schedule** | Inject writes `bgp_flap_schedule.jsonl` (`--schedule-out`) |
| **Smoke** | Δ ≥8 · ≥4 rows with positive step · schedule events present |

### L6 CE-SLA — continuous rogue plateau

| Rule | Detail |
| --- | --- |
| **Shape** | Continuous bronze rogue iperf @ `rogue_mbit` + gold TT&C probe — **no** kill/restart steps |
| **Forbidden for campaign** | `--coarse` pulsed bitrate handoff (same util pulsing failure as old L5) |
| **Smoke** | util residency without high→idle drops ≥5 · util_max ≤ 1.25× HTB root |

### COMPOUND — both legs visible

| Rule | Detail |
| --- | --- |
| **Smoke pair** | rain_fade + cpu_stress |
| **Gate** | latency_max ≥15 **and** cpu_usage_user max ≥30 with residency under overlap |
| **Note** | Quiet-leg drowning vs Q2 argmax is Lane B (architecture) — smoke only proves both physics fire |

---

## L5 inject shape (tc-ramp + plateau) — CAPTURE_CONTRACT 2026-08-06

- **Default:** continuous iperf offer (**≥2× end_mbit**) + **CE `veth-cea-pe` HTB** stepping rate/ceil + plateau ≥30–45 s at `end_mbit` (L5 ends `[12,16,20,24,28,30,32,34]`), then restore.
- **Why not PE `1:15` alone:** CE→PE util is IPsec/MPLS-encapped on eth0 → filters miss → traffic lands in **BE `1:20`** (nominal ceil **24**). Changing PE 1:15 is a no-op for measured util.
- **BE lift:** during the inject window, temporarily raise PE `1:20` ceil → **40** (parent) so CE shape is visible on eth0; restore `5/24` on EXIT / `--clear`. Mirror PE `1:15` for audit/twin only.
- **Schedule:** `util_ceil_schedule.jsonl` includes `htb_payload_ceil_mbps`, `end_mbit`, `offer_mbit`, `shape=ce_veth`, `be_lifted`.
- **Q2 labels:** `5A` = scheduled ceil ∈ `[0.5·end, end)` · `5B` = ceil ≥ end (not raw Mbps bands alone).
- **Live feature:** `htb_payload_ceil_mbps` exporter → Prom → `FEATURE_COLS`.
- **Chaos util phase:** `end_mbit=24` (off-nominal vs idle payload ceil 34).
- Smoke **fails** if util≫root ceil, near-ceil residency &lt;15 s, or high→idle drops ≥5.
- `--coarse` / `--iperf-steps` = debug only — **not** for util TTI train / long campaign.
---

## Smoke gate (30–60 min) — before 12.5 h

One each of **L1–L6 + one COMPOUND** under this contract. Row-audit primary trajectories:

1. Asymmetry: logged = \|gre−eth0\| (err ≪ 1 ms every row).
2. Timestamps: dense 1 Hz after align; capture gap_count disclosed.
3. L2: `cpu_usage_user` plateau · L3: flap counter rate · L4: loss ramp · L5/L6: util residency (not pulsed) · COMPOUND: both legs.

Only then: long campaign → retrain → score vs **current promote bar** (not stale 0.884 as train target).

---

## Full campaign trim (locked 2026-08-05)

| Block | Rule |
| --- | --- |
| **Trim** | L2/L3 inject wall-clock (fast-onset) · L1/L4 variant **count** 8→4 (already strong) |
| **Keep** | L5×8 + `plateau_sec≥40` · L6×4 continuous hold · COMPOUND×8 · chaos_holdout **7200 s** |
| **Parallel** | Pi ∥ GNS3 (same trimmed plan both fabrics) |
| **Window floor** | Do not cut so hard that a severity class falls back to ~20–40 train windows |
| **Post-run check (mandatory)** | `python -m predictive.check_q1_window_floors --protocol-dir <stamp>` — soft≥100 / hard≥50 for latency·jitter·**loss** |
| **L4×4 ⇒ loss densify** | Prior stamp: loss usable was **41@×8 stride5** (thin) · **~25@×4 stride5** (fails hard) · **115@×4 stride1** (clears soft). Q2 chaos strength ≠ Q1 window count. **Lock stride-1** for loss TTI train windows after this trim (same pattern as jitter densify). |

**Pre-flight (prior `full_variants_pi_*`, not assumption):** latency×4≈417 · jitter×4≈146 (stride5) / 725 (stride1) · loss×4≈25 (stride5) / **115 (stride1)**.

Code: `FULL_N_VARIANTS` / grids in `predictive/variant_recipes.py` · floor gate `predictive/check_q1_window_floors.py`.

**Launch (operator go only — do not auto-start):**

```bash
# Prepare (dry plan + preflight; does not capture)
bash predictive/prepare_capture_contract_full.sh --fabric pi

# When told to go (~9.25 h):
bash predictive/prepare_capture_contract_full.sh --fabric pi --stamp <STAMP> --go

# After ACTIVE_DONE:
bash predictive/post_capture_contract_full.sh --fabric pi --stamp <STAMP>
```

Pi-first by default. Optional twin: same with `--fabric gns3` (parallel or later).

---

## Code map

| Area | Files |
| --- | --- |
| Edge emit util + asymmetry | `lab/telemetry-pipeline/scripts/sdwan_tunnel_stats.sh` |
| Prom queries | `predictive/prom_export.py` |
| Capture derive + gaps | `predictive/capture_live.py` |
| Q1 ETA + align default | `predictive/q1_windows.py` |
| Q2 drop stale asym | `predictive/q2_windows.py` |
| Preprocess | `predictive/preprocess.py` (derive / overwrite) |
| L5 tc-ramp + `--schedule-out` | `scripts/inject_util_congestion.sh` |
| Util schedule-gated labels | `predictive/util_schedule.py` |
| L6 CE continuous plateau | `scripts/inject_ce_sla_conflict.sh` (`--hold-sec`; `--coarse` debug) |
| L3 BGP flap schedule | `scripts/inject_bgp_flap.sh` (`--schedule-out`) |
| Smoke grade | `predictive/verify_variant_smoke.py` · `predictive/run_capture_contract_smoke.sh` |
| Ceiling constant | `predictive/fabric_baseline.py` |
| Confound receipt | `…/contract_smoke_l5_tcramp_*/UTIL_CONFOUND_LABELING.md` |
| Full-label smoke stamp | `…/contract_smoke_full_20260805T025000Z/` |

---

## Explicit non-goals (this contract)

- Multi-label presence (Lane B)
- O4 multi-candidate / graph engine (Lane C)
- Promoting a new Q2 over frozen `d2` without sealed chaos_final under the promote bar
