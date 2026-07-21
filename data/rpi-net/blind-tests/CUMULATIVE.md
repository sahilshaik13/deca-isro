# Adversarial blind tests — cumulative

**Folder:** `data/rpi-net/blind-tests/` (artifacts under `blind_*` dirs)  
**This file is the only blind scoreboard you need.** Per-run write-ups are archived under [`docs/results/archive/`](../../../docs/results/archive/).

**Related:** [Live trust cumulative](../live/CUMULATIVE.md) · [Data runs cumulative](../runs/CUMULATIVE.md)

---

## How to read this

Adversarial blinds inject **real sealed faults**. They measure **detection**, not calm cry-wolf.  
Exam PASS ≠ blind success. Quote both.

**Two-sentence framing:** we closed false alarms (see live cumulative); detection has a measured cost when we taught near-misses to stay healthy.

---

## Scoreboard (all adversarial blinds)

| Run | Date (IST) | Detect | Class first→eventual | Conf lead | NM FA | Spurious | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `blind_20260716_1537_60m` | 16 Jul 15:37 | **4/4** | 50%→100% | 2.6 min | 1/1 | **49** | Night 1 |
| `blind_20260716_1924_60m` | 16 Jul 19:24 | **5/5** | 80%→100% | 3.0 min | 2/2 | **17** | Ultimate leg 1; BGP densify live |
| `blind_20260718_0848_60m` | 18 Jul 08:48 | **3/4** | 75%→75% | 4.6 min | **0/2** | **3** | Missed PE2 **VRF**; post–spec-data model |
| `blind_20260718_2219_60m` | 18 Jul 22:19 | **4/4** | **100%→100%** | 4.8 min | 0/0 | **6** | Post–VRF-recall; **no VRF drawn** |
| `blind_vrfcheck_20260719_0210_45m` | 19 Jul 02:10 | **2/3** | 33%→33% | 5.0 min | **0/2** | **0** | Compound=1 (forced VRF): VRF **as tunnel**; BGP **missed** |
| `blind_echo_20260719_1102_45m` | 19 Jul 11:02 | **3/3** | **100%→100%** | 6.3 min | 1/2 | **0** | Echo origin-lock on; PE1 cong/tunnel only |
| `blind_compound_bgp_route_flap_20260719_1239_40m` | 19 Jul 12:39 | **2/2** | 50%→50% | 6.2 min | 0/1 | **0** | Dual: station1 BGP scored **as VRF** (inverse contamination; echo on, **VRF lock off**) |
| `blind_compound_congestion_breach_20260719_1256_40m` | 19 Jul 12:56 | **1/2** | 50%→50% | 10.5 min | 0/1 | **3** | Dual: VRF **missed**; 3× spurious station2 **VRF** (gates on) |
| `blind_compound_tunnel_degradation_20260719_1317_40m` | 19 Jul 13:17 | **1/2** | 50%→50% | 2.3 min | 0/1 | **0** | Dual: VRF **missed** (both gates on) |
| `blind_vrf_isolated_20260719_1333_45m` | 19 Jul 13:33 | **2/2** | **100%→100%** | 0.1 min* | 0/1 | **0** | Isolated VRF; both gates — leads **−3.4 / +3.6 min** |
| `blind_compound_bgp_recheck_20260719_1516_40m` | 19 Jul 15:16 | **2/2** | 50%→50% | 1.2 min | 0/1 | **1** | Both gates on: **no** s1 VRF; BGP **as tunnel**; VRF ok; 1 spurious s2 VRF |
| `blind_compound_tunnel_recheck_20260719_2012_40m` | 19 Jul 20:12 | **1/2** | 50%→50% | 7.6 min | 0/0 | **0** | Post-overlap w1; **promote FAIL** — old model; tunnel **HIT**; VRF **silent miss** |
| `blind_compound_tunnel_recheck_20260720_0154_40m` | 20 Jul 01:54 | **1/2** | 50%→50% | — | 0/0 | **0** | Post-overlap w2; promote **FAIL**; tunnel **HIT**; VRF **miss** |
| `blind_compound_bgp_recheck_20260720_0213_40m` | 20 Jul 02:13 | **1/2** | 50%→50% | −0.6 min | 0/0 | **0** | Post-overlap w2; BGP **miss**; VRF **hit** (class swap vs tunnel blind) |

Compound rollup: [`compound_series_20260719_rollup.md`](compound_series_20260719_rollup.md).

---

## Finding: station2 “spurious” = cross-host echo (not calm flicker)

Checked **all 9** station2 spurions across `0848` (3) + `2219` (6) against the real station1 timeline: **9/9** same-class as an active or just-cleared station1 fault (during, or ~2–3.5 min after). Two of the six on `2219` **led** station1’s confirm by ~15–90 s (receiver telemetry lights first).

Station2 is the iperf3 receiver for station1’s traffic — a real PE1 link fault shows up in station2’s received-path loss/jitter. The model was treating that echo as an independent station2-originated fault.

**Fix (operator):** `deca_live_operator.py` origin-lock — station2 never *confirms* `congestion_breach` / `tunnel_degradation` (advisory may still name them). Lab injections attribute those classes to station1 only. Flag `--no-cross-host-echo-suppress` disables; `--cross-host-echo-confirm-window` uses the narrower active/recent-confirm rule (misses leading echoes). Selfcheck: `python scripts/deca_live_operator.py --selfcheck-echo`.

**Live proof (`blind_echo_20260719_1102_45m`):** 3× PE1 cong/tunnel, origin-lock on → **0 spurious**, **0** station2 shared-link `confirmed_raise`, **8** ticks where the gate held a station2 confirm (echo present, not declared). Detection **3/3** class-correct. One NM FA (`nm02` congestion on station1) sat on the heels of `e01` clear — post-fault bleed into bait, not an echo issue.

---

## Open questions (four buckets — do not collapse)

1. **Cross-host echo (station2 → PE1 classes)** — **closed.** Origin-lock proved (`blind_echo_*`). Echo gate was **on** for all compound runs (verified in `operator_feed.log`).

2. **Compound VRF leg miss** — PE1 cong/tunnel + VRF overlap: VRF **missed 2/3** (cong, tunnel compounds). Isolated VRF **2/2** with gates on — overlap is the gap, not bare recall.

3. **Inverse cross-host contamination (station1 → PE2 class)** — **VRF lock works.** Re-check (`blind_compound_bgp_recheck_*`, both gates on): **0** station1 `vrf_leakage` confirms. First BGP compound had s1 VRF without lock. Remaining compound class error on this leg: BGP declared **`tunnel_degradation`** on station1 (not BGP, not VRF).

4. **VRF recall presentation** — Binary recall **proved** isolated (`blind_vrf_isolated_*`: **2/2**, class **100%**). Per-leg leads: **−3.4 min** and **+3.6 min** (mean 0.1 min hides one near-simultaneous confirm). Quote leads when presenting, same as severity.

5. **Spurious station2 VRF outside windows** — Re-check: **1** (same pattern as cong compound). Gates on; not echo.

### Cong compound “3 spurions” — corrected

Not pre-gate echo noise. Gates were on; **0** station2 cong/tunnel confirms. The 3 spurions are **station2 `vrf_leakage` confirms outside scored windows** (07:26–07:27) — a different failure mode (spurious VRF, not echo). Echo gate held 2 ticks; VRF origin-lock held 2 station1 vrf attempts on that run.

### Also open (not the main chase)

| Item | Status |
| --- | --- |
| **Severity calibration** | Do not ship — bucket agreement / Pearson weak across nights |
| **Post-fault NM bleed** | Occasional (`echo` night 1/2 NM FA right after a real clear) |
| **Campaign inject retry** | `deca_vrf_recall_campaign.py` has no retry on failed inject (ops note) |

---

## Chase order

1. ~~Prove cross-host echo suppress on a fresh control + blind.~~ **Done 19 Jul.**  
2. ~~Deliberate compound-fault series.~~ **Done 19 Jul** — see four buckets above.  
3. ~~Isolated VRF proof blind.~~ **Done** — 2/2 binary recall; quote per-leg leads.  
4. ~~BGP+VRF re-check with both gates.~~ **Done** — VRF inverse contamination **fixed**; BGP→tunnel class swap remains under overlap.  
5. **Compound overlap** — w1+w2 campaigns **done** (18 compounds total). **Promote still FAIL** (0.704). Blinds: tunnel compound VRF **miss** persists; BGP compound now **VRF hit / BGP miss** — one-leg detection under overlap, not solved.

Gate verification: `grep -E 'echo suppress|vrf origin-lock' data/rpi-net/live/<run_id>/operator_feed.log`

Diagnostic: `python scripts/deca_vrf_tunnel_diagnostic.py`  
Gates selfcheck: `python scripts/deca_live_operator.py --selfcheck-gates`

---

## Severity (do not ship)

Latest nights: bucket agreement low / Pearson negative. Never quote bucket % alone.

---

## Update rule

After every new `blind_*` grade: add one row here. Do not create a new top-level markdown in `docs/results/`.
