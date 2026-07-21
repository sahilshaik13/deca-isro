# Specificity exam v2 — durability playlist

**Design:** [`../DECA_SPECIFICITY_EXAM.md`](../DECA_SPECIFICITY_EXAM.md)  
**Playlist:** [`scripts/playlists/specificity_exam_v2.json`](../../scripts/playlists/specificity_exam_v2.json) — different calm lengths and near-miss holds than v1; **4** baits; never used to diagnose a fix.

Same pass bar as v1: 0 NM FA, 0 calm spurious, 0 BGP. This run checks whether the 18 Jul v1 PASS generalizes.

## Live attempt — 18 Jul 2026 — **PASS**

| Field | Value |
| --- | --- |
| **Run ID** | `specificity_exam_v2` (archived `specificity_exam_v2_20260718_1752`) |
| **Date / time** | Saturday **18 July 2026**, **17:17 – ~17:52 IST** (11:47 – ~12:22 UTC) |
| **Seed** | `12114` |
| **Model** | Post–spec-data promote (pre–VRF-recall retrain) |
| **Exam result** | **PASS** |
| **Archive** | [`data/rpi-net/blind-tests/specificity_exam_v2_20260718_1752/`](../../data/rpi-net/blind-tests/specificity_exam_v2_20260718_1752/) |

| Check | Result |
| --- | ---: |
| Near-miss FA | **0 / 4** |
| Calm spurious | **0** |
| BGP confirms | **0** |

All 10 phases PASS (warm + calm_a–e + nm01–04).

### Vs v1

| | Exam v1 PASS (same day, morning) | **Exam v2** |
| --- | ---: | ---: |
| Playlist | diagnosed / fixed against | **never used to diagnose** |
| Near-miss baits | 3 | **4** |
| NM FA / calm spurious / BGP | 0 / 0 / 0 | **0 / 0 / 0** |

**Interpretation:** Specificity trust bar holds on a second, unseen playlist — not only on the paper we studied. (Post–VRF-recall promote must re-check v1+v2 before calling that stack durable.)
