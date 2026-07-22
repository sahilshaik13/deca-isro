# Lab ops (laptop ↔ CE–PE–CE Pi cluster)

Laptop-side helpers for the physical DECA station network. These used to live
scattered in `$HOME`; they belong in-repo so the lab is reproducible.

Run from the **laptop on the lab LAN** (USB eth typically `192.168.50.1`).

### `deca_ops.sh` — start here

[`deca_ops.sh`](deca_ops.sh) consolidates five overlapping scripts (`check_stations.sh`,
`check_step7.sh`, `deca_diagnostic.sh`, `deca-heal-telemetry.sh`, `apply_boot_fix.sh`)
into one tool with three subcommands, a single password prompt, and a real
PASS/FAIL/WARN summary at the end instead of five separate scroll-and-squint runs:

```bash
bash lab/deca_ops.sh check          # health check (default if no arg given)
bash lab/deca_ops.sh heal           # restart failed services, then re-check
bash lab/deca_ops.sh install-boot   # apply the boot-autostart fix, then re-check
bash lab/deca_ops.sh all            # install-boot, then heal
```

It also fixes one real bug found while merging: `check_stations.sh` SSHed to
`s1`/`s2`/`s3`, but this lab's `~/.ssh/config` only defines `station1`/`station2`/
`station3` — those calls never resolved. `deca_ops.sh` uses the real aliases
throughout.

The five originals below are **kept, not deleted** — `link_home.sh` symlinks them
into `$HOME` and some docs still say `~/deca_diagnostic.sh`. Prefer `deca_ops.sh`
for anything new; treat the individual scripts as legacy/superseded.

| Script | Role |
| --- | --- |
| [`deca_diagnostic.sh`](deca_diagnostic.sh) | *(superseded by `deca_ops.sh check`)* Master health check (VPN ping + Telegraf 3/3) |
| [`check_stations.sh`](check_stations.sh) | *(superseded — also had the `s1`/`s2`/`s3` bug above)* Topology / convergence smoke check |
| [`check_step7.sh`](check_step7.sh) | *(superseded by `deca_ops.sh check`, item [6])* Deep CE-A → CE-B data-plane check |
| [`trace_step7.sh`](trace_step7.sh) | Trace traffic from CE-A (not merged — one-off packet trace, not a recurring check) |
| [`deca-deploy.sh`](deca-deploy.sh) | Plug-and-play deploy (namespaces + ordering + watchdog) |
| [`apply_boot_fix.sh`](apply_boot_fix.sh) | *(superseded by `deca_ops.sh install-boot`)* Apply sticky boot fixes on the Pis |
| [`deca-heal-telemetry.sh`](deca-heal-telemetry.sh) | *(superseded by `deca_ops.sh heal`)* Quick heal when `[7/8]`/`[8/8]` fail after partial boot |
| [`startupppp`](startupppp) | Enable FRR / strongSwan / Telegraf on PE stations |
| [`forwardss`](forwardss) | Policy-routing fix for CE namespace return path |
| [`run_traffic.sh`](run_traffic.sh) | Laptop iperf background traffic (**do not** combine with fault-campaign baseline) |
| [`cisco_scraper.py`](cisco_scraper.py) | Ad-hoc Cisco DevNet sandbox scrape (see also `scripts/cisco_scraper.py` for the DATA_GEN path) |

Related repo scripts (already under `scripts/`): `deca_deploy_stations.sh`,
`deca_heal_telemetry.sh`, `deca_fix_prom_vpn.sh`. Prefer **this folder** for
day-to-day laptop ops; prefer `scripts/` for campaign / ML pipeline entrypoints.

Full topology runbook: [`docs/STATION_NETWORK_SETUP.md`](../docs/STATION_NETWORK_SETUP.md)

## Quick start

```bash
cd ~/deca-isro   # or your clone path
bash lab/deca_ops.sh check            # expect all PASS
bash lab/deca-deploy.sh               # (re)deploy sticky config when needed
bash lab/deca_ops.sh heal             # if Telegraf / VPN ping failed
```

## Optional: keep old `~/…` shortcuts

Docs and muscle memory still mention `~/deca_diagnostic.sh`. After a clone, link
home names to this folder once:

```bash
bash lab/link_home.sh
```

That creates/updates symlinks such as `~/deca_diagnostic.sh` → `lab/deca_diagnostic.sh`.

## Do not commit

- `nohup.out` — runtime log dump; ignored by `.gitignore`
