# GNS3 dual-fabric lab (thin repo tree)

Heavy artifacts live on the **external drive only** — never on the ~50 GB root:

```text
/media/brain/Shaik's/gns3/
  venv/         — gns3-server + gns3-gui (pip)
  images/
  projects/
  configs/gns3_server.conf
  appliances/
  symbols/
  captures/     — Wireshark / packet dumps (not /tmp, not ~)
  docker/       — optional Docker data-root (after migrate script)
  bin/          — wrappers
```

Repo `lab/gns3/` holds scripts and docs only — nothing large.

**Root disk killers (avoid):** Docker images under `/var/lib/docker` (FRR/Alpine/iperf/TRex), `/tmp/GNS3.*` (Wireshark temps while captures run), pip caches, Wireshark pcaps in home.

```bash
bash lab/gns3/ensure_storage.sh
# Emergency when root hits 100%: stop captures + wipe /tmp/GNS3.*
bash lab/gns3/reclaim_root_disk.sh
# start_gns3.sh sets TMPDIR → …/gns3/tmp (restart GUI to pick it up)
# One-time (needs sudo): move Docker off root → Shaik's
bash lab/gns3/migrate_docker_to_external.sh          # dry-run
bash lab/gns3/migrate_docker_to_external.sh --apply  # stop docker, rsync, data-root=
```

Wireshark: apt binary may stay on root (~100 MB); **save all captures** under `…/gns3/captures/`. Stop link captures when done — leaving them on fills `/tmp` and root. Do **not** pull the TRex image — NOC uses iperf3 only.

## Topology (project DECA — 16 nodes)

```bash
python3 lab/gns3/build_deca_topology.py --wipe   # full multi-PE / dual-P rebuild
```

Station-faithful fabric: **CORE-N/S · PE1/2/3 · 8 CEs · IPERF-A/B**  
Chaos stack (Pi twin, **no TRex**): **iperf3 ToS TCP/UDP via HTB** (TT&C 1M/`0x88`/:5004 · Payload 50M/`0x80`/:5006 · Admin 20M TCP/:5201) + **NetEM rain/loss** on underlay (not PE HTB) + **stress-ng** + **BGP soft-clear** + **util ramp** — see [`docs/shared_fault_book.json`](../../docs/shared_fault_book.json).  
Paths: vrf-mission (PE↔CORE) + vrf-admin direct PE↔PE + chaos gens.

See [TOPOLOGY.md](TOPOLOGY.md).

**Host packages (optional, needs sudo):** `ubridge` (Ethernet switch/hub), `dynamips` (legacy IOS). Docker nodes work without them.

## Install (no sudo; uses external drive)

```bash
bash lab/gns3/ensure_storage.sh
bash lab/gns3/install_gns3.sh     # ~2.2.61 into .../gns3/venv
bash lab/gns3/start_gns3.sh       # server on :3080
bash lab/gns3/start_gns3.sh --gui # optional GUI if DISPLAY set
```

Server config already points images/projects at the external paths.

When the minimal topology exports Prom with `fabric="gns3"`, touch:

```bash
touch "/media/brain/Shaik's/gns3/projects/DECA_READY"
```

so the NOC **Simulation source** toggle marks GNS3 ready.

## Flow 1 + inject adapters

Same path as Pi as-built: chaos → branch CE → HTB/AAR/IPsec → PE →
vrf-mission (GRE/MPLS→CORE-N) or vrf-admin (eth0) → DC/Hub CE.
**SLAs aligned** with Pi (see `GET /api/v1/fabric` · policy §1c · [`EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md)).

### NOC-first (no GNS3 GUI required)

```bash
bash lab/gns3/start_gns3.sh          # server only — skip --gui
# Start all nodes once (API or one-time GUI), then:
touch "/media/brain/Shaik's/gns3/projects/DECA_READY"
python3 lab/gns3/exporters/gns3_path_exporter.py &   # :9275 live gauges
# NOC :3000 → Simulation source = GNS3 → Traffic → Simple faults → Decide
```

`lab/gns3/inject/<fault_id>.sh` — same five faults as Pi Simple faults (+ `util_congestion.sh` for L5).
`lab/gns3/traffic_control.sh` — Start/Stop ToS iperf from dashboard (`POST /api/v1/traffic/*`).
`fault_demo.py` dispatches here when active fabric is `gns3`.

Apply / audit edge policies:

```bash
bash lab/gns3/apply_sla_htb.sh
FABRIC=gns3 bash lab/audit_edge_policies.sh
```

## Protocol data campaign (separate from Pi)

GNS3 corpus lives under `data/deca/predictive/protocol_gns3/` (Prom `:9091`).  
Does **not** touch the Pi stamp on `:9090`.

```bash
# Ensure exporter + Prom :9091, then pilot
python3 lab/gns3/exporters/gns3_path_exporter.py &   # if :9275 down
DECA_FABRIC=gns3 bash predictive/run_protocol_campaign_gns3.sh --pilot
```

See [`predictive/README.md`](../../predictive/README.md) · SLA: [`SLA.md`](SLA.md) · mesh demo: `run_ce_mesh_sdwan_demo.sh`.

## Rules

- Refuse to start GNS3 if `/media/brain/Shaik's` is unmounted
- Quote paths (apostrophe in `Shaik's`)
- Do not put GNS3 images, Docker data-root, or pcaps on the ~50 GB root disk
- Leave Pi protocol campaign alone while it runs; rehearse GNS3 faults here
- If root is &gt;90% full: `bash lab/gns3/migrate_docker_to_external.sh --apply` (sudo)