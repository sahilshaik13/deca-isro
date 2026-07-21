# Live trust instruments — cumulative

**Folder:** `data/rpi-net/live/` (active runs) · graded copies also under `data/rpi-net/blind-tests/`  
**This file is the only live trust scoreboard you need** (specificity exams + all-healthy controls).

**Related:** [Blind cumulative](../blind-tests/CUMULATIVE.md) · [Data runs cumulative](../runs/CUMULATIVE.md)

---

## How to read this

These runs inject **no real faults** (or only aborted near-miss baits). They measure **cry-wolf / specificity**.  
**Exam PASS does not mean the system detects real faults.** Detection lives in the blind cumulative.

Pass bar (exams): NM FA **0**, calm spurious **0**, BGP confirms **0**.

---

## Specificity exams

| Run | Date (IST) | Playlist | NM FA | Calm spur | BGP | Result |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `specificity_exam_v1_20260717_1022` | 17 Jul 10:22 | v1 | 1/3 | 2 | 0 | **FAIL** |
| `specificity_exam_v1_20260718_0848` | 18 Jul 08:17 | v1 | **0/3** | **0** | 0 | **PASS** |
| `specificity_exam_v2_20260718_1752` | 18 Jul 17:17 | v2 (unseen) | **0/4** | **0** | 0 | **PASS** |
| `specificity_exam_v1_20260718_2107` | 18 Jul 20:36 | v1 post–VRF-recall | **0/3** | **0** | 0 | **PASS** |
| `specificity_exam_v2_20260718_2142` | 18 Jul 21:07 | v2 post–VRF-recall | **0/4** | **0** | 0 | **PASS** |

Playlists: `scripts/playlists/specificity_exam_v1.json`, `specificity_exam_v2.json`.

---

## All-healthy controls

| Run | Date (IST) | Budget | NM FA | Spurious | BGP among spur |
| --- | --- | ---: | ---: | ---: | ---: |
| `control_20260716_1924_60m` | 16 Jul 20:41 | 60m | 3/4 | **21** | **18** |
| `control_fp_check2` | 17 Jul 09:30 | 30m | 4/4 | **5** | **0** |
| `control_20260718_0848_60m` | 18 Jul 09:51 | 60m | **0/4** | **0** | 0 |
| `control_after_vrf_20260718_2142` | 18 Jul 21:42 | 30m | **0/4** | **0** | 0 |
| `control_echo_20260719_1027_30m` | 19 Jul 10:27 | 30m | **0/4** | **0** | 0 |

---

## Story in one page

1. **16 Jul control** — Catch‑9 cry-wolf (21/hour, mostly invented BGP).  
2. **BGP densify + evidence gate** — BGP invention gone; NM FA still bad (`fp_check2`).  
3. **Exam v1 FAIL → data campaign → PASS** — calm/NM trust bar cleared.  
4. **Exam v2 + post–VRF-recall re-sits** — still PASS (specificity held after recall retrain). Exam v2 exists specifically as an unseen second playlist so a PASS is not “the playlist we diagnosed against.”  
5. **Controls 18–19 Jul** — clean (0 NM FA, 0 spurious), including post–echo-gate `control_echo_20260719_1027_30m`.

---

## Operator gate (post–2219 finding)

Blind spurions on station2 were **cross-host echo** of station1 shared-link faults (see blind cumulative). Live operator origin-locks station2 confirms of `congestion_breach` / `tunnel_degradation`.

**Trust re-check after gate:**
- Control `control_echo_20260719_1027_30m` — **0/4** NM FA, **0** spurious (held).
- Echo-proof blind `blind_echo_20260719_1102_45m` — **3/3** detect, **0** spurious.
- Operator gates (19 Jul): **echo origin-lock** (station2 no cong/tunnel confirm) + **VRF origin-lock** (only station2 confirms `vrf_leakage`). Isolated VRF proof blind queued after compound series.

---

## Update rule

After every exam/control grade: add one row here. Active operator dirs stay under `live/<run_id>/`; archive graded copies to `blind-tests/`.
