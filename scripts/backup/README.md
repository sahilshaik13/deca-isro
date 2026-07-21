# Campaign script backups

Frozen copies of lab campaign drivers **before / around** the specificity-data loop (17–18 Jul 2026). Live scripts stay in `scripts/`.

| File | What it is |
| --- | --- |
| `deca_fault_campaign.py.bak_pre_spec_20260718` | Last **git HEAD** fault campaign (before PE2 near-miss, fixed `hold_s`, pulse lock) |
| `deca_fault_campaign.py.bak_working_20260718` | Working tree copy after specificity injector edits (snapshot at backup time) |
| `deca_circumstance_campaign.py.bak_20260715` | Circumstance campaign as of last commit (`circ_v2` era) |

Restore example:

```bash
cp scripts/backup/deca_fault_campaign.py.bak_pre_spec_20260718 scripts/deca_fault_campaign.py
```

Do **not** delete these when editing live campaigns; add a new dated `.bak_*` if you change injectors again.
