# Lab ops (laptop ↔ CE–PE–CE Pi cluster)

Laptop-side helpers for the physical DECA station network. These used to live
scattered in `$HOME`; they belong in-repo so the lab is reproducible.

Run from the **laptop on the lab LAN** (USB eth typically `192.168.50.1`).

| Script | Role |
| --- | --- |
| [`deca_diagnostic.sh`](deca_diagnostic.sh) | Master health check (VPN ping + Telegraf 3/3) |
| [`check_stations.sh`](check_stations.sh) | Topology / convergence smoke check |
| [`check_step7.sh`](check_step7.sh) | Deep CE-A → CE-B data-plane check |
| [`trace_step7.sh`](trace_step7.sh) | Trace traffic from CE-A |
| [`deca-deploy.sh`](deca-deploy.sh) | Plug-and-play deploy (namespaces + ordering + watchdog) |
| [`apply_boot_fix.sh`](apply_boot_fix.sh) | Apply sticky boot fixes on the Pis |
| [`deca-heal-telemetry.sh`](deca-heal-telemetry.sh) | Quick heal when `[7/8]`/`[8/8]` fail after partial boot |
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
bash lab/deca_diagnostic.sh          # expect all green
bash lab/deca-deploy.sh              # (re)deploy sticky config when needed
bash lab/deca-heal-telemetry.sh      # if Telegraf / VPN ping failed
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
