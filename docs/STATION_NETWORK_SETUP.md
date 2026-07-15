# DECA Station Network Setup

## Start
- To Check the status of the stations 
```bash
check stations
```
---

Physical CE–PE–CE lab on three Raspberry Pis + laptop orchestrator. This is the **authoritative station networking reference** for plug-and-play restore and ISRO handover.

**Apply / restore everything:**

```bash
bash ~/deca-isro/scripts/deca_deploy_stations.sh
# optional alias:
# cp -f ~/deca-isro/scripts/deca_deploy_stations.sh ~/deca-deploy.sh && bash ~/deca-deploy.sh

bash ~/deca_diagnostic.sh   # expect [7/8] VPN ping + [8/8] 3/3 Telegraf
```

Cold boot: power-cycle all three Pis, wait **≥120s** (watchdog sleeps 60s), then re-run the diagnostic.

---

## 1. Topology

```
                     ┌─────────────────────────────┐
                     │  Laptop (orchestrator)      │
                     │  USB eth  192.168.50.1/24   │
                     │  Prometheus :9090           │
                     │  scrapes :9273 on each Pi   │
                     └─────────────┬───────────────┘
                                   │ 192.168.50.0/24 lab LAN
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
┌────────▼────────┐      ┌─────────▼────────┐      ┌────────▼────────┐
│ station1 (PE1)  │      │ station3 (CORE)  │      │ station2 (PE2)  │
│ 192.168.50.10   │◄────►│ 192.168.50.30    │◄────►│ 192.168.50.20   │
│ lo 10.1.1.1     │ OSPF │ lo 10.1.3.1      │ OSPF │ lo 10.1.2.1     │
│ FRR + IPsec     │ LDP  │ FRR (P-core)     │ LDP  │ FRR + IPsec     │
│ VRF vrf-mission │ BGP  │                  │ BGP  │ VRF vrf-mission │
└────────┬────────┘      └──────────────────┘      └────────┬────────┘
         │ veth-pe-cea                                    │ veth-pe-ceb
         │ 10.10.1.2/30                                   │ 10.10.2.2/30
┌────────▼────────┐                              ┌────────▼────────┐
│ netns ce-a      │      VPN dataplane over      │ netns ce-b      │
│ 10.10.1.1/30    │◄──── MPLS + IPsec SD-WAN ───►│ 10.10.2.1/30    │
│ lo 10.100.1.1/32│      ping CE-A → 10.100.2.1  │ lo 10.100.2.1/32 │
└─────────────────┘                              └─────────────────┘
```

| Role | Host | Lab LAN | Loopback / RID | CE netns |
| --- | --- | --- | --- | --- |
| PE1 | `station1` | `192.168.50.10/24` | `10.1.1.1` | `ce-a` → CE-A |
| PE2 | `station2` | `192.168.50.20/24` | `10.1.2.1` | `ce-b` → CE-B |
| CORE | `station3` | `192.168.50.30/24` | `10.1.3.1` | — |
| Laptop | `brain` | `192.168.50.1/24` | — | — |

**SSH (`~/.ssh/config`):**

```
Host station1
    HostName 192.168.50.10
    User station1

Host station2
    HostName 192.168.50.20
    User station2

Host station3
    HostName 192.168.50.30
    User station3
```

**IPsec overlay:** `deca-sdwan` between PE1↔PE2. Traffic selectors include CE subnets / loopbacks:

`10.10.1.0/30 10.100.1.1/32  ===  10.10.2.0/30 10.100.2.1/32`

**Diagnostic gold path:** from `ce-a`, `ping 10.100.2.1` (script: `~/deca_diagnostic.sh` step 7).

---

## 2. Addressing cheat sheet

| Prefix / address | Where | Purpose |
| --- | --- | --- |
| `192.168.50.0/24` | eth0 all nodes | Management / Telegraf / SSH |
| `10.1.1.1`, `10.1.2.1`, `10.1.3.1` | PE/CORE loopbacks | OSPF / BGP / LDP router-IDs |
| `10.10.1.0/30` | PE1 ↔ ce-a | Local CE attachment |
| `10.10.2.0/30` | PE2 ↔ ce-b | Local CE attachment |
| `10.100.1.1/32` | ce-a `lo` | CE-A VPN identity |
| `10.100.2.1/32` | ce-b `lo` | CE-B VPN identity (iperf3 target) |
| `vrf-mission` | PE1 / PE2 | Mission VRF for CE traffic |
| Telegraf | each Pi `:9273` | Prometheus scrape |
| Route-target | `65001:100` | VPN RT (campaign / FRR) |

---

## 3. Services per station

| Unit | station1 | station2 | station3 |
| --- | :---: | :---: | :---: |
| `deca-ns.service` | ✓ CE-A | ✓ CE-B | — |
| `frr.service` | ✓ | ✓ | ✓ |
| `strongswan-starter` | ✓ | ✓ | — |
| `telegraf` | ✓ | ✓ | ✓ |
| `chrony` | ✓ | ✓ | ✓ |
| `deca-watchdog.service` | ✓ | ✓ | ✓ |

Ordering on PE1/PE2:

- `deca-ns` **Before** `frr` and `strongswan-starter`
- `frr` / `strongswan-starter` **Requires** + **After** `deca-ns` (drop-ins)

---

## 4. Systemd units (code)

### 4.1 station1 — `/etc/systemd/system/deca-ns.service`

```ini
[Unit]
Description=Setup CE-A Network Namespace
After=systemd-networkd.service network-online.target
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=2
ExecStartPre=/bin/bash -c "ip link del veth-pe-cea 2>/dev/null; ip link del veth-pe-ce1 2>/dev/null; ip netns del ce-1 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-a 2>/dev/null; ip netns list | grep -q \"^ce-a\" || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "ip netns add ce-a && ip link add veth-pe-cea type veth peer name veth-cea-pe && ip link set veth-cea-pe netns ce-a && ip link set veth-pe-cea master vrf-mission && ip addr add 10.10.1.2/30 dev veth-pe-cea && ip link set veth-pe-cea up && ip netns exec ce-a ip addr add 10.10.1.1/30 dev veth-cea-pe && ip netns exec ce-a ip link set veth-cea-pe up && ip netns exec ce-a ip link set lo up && ip netns exec ce-a ip addr add 10.100.1.1/32 dev lo && ip netns exec ce-a ip route add default via 10.10.1.2 && ip rule add from 10.100.2.1/32 iif eth0 lookup 100 && sysctl -w net.ipv4.conf.veth-pe-cea.forwarding=1 && ip netns exec ce-a iptables -F && ip netns exec ce-a iptables -P INPUT ACCEPT && ip netns exec ce-a iptables -P OUTPUT ACCEPT && ip netns exec ce-a iptables -P FORWARD ACCEPT"
ExecStop=/bin/bash -c "ip netns del ce-a 2>/dev/null; ip link del veth-pe-cea 2>/dev/null; true"

[Install]
WantedBy=multi-user.target
```

**Must have exactly one `ExecStartPre=`.** Duplicate lines (from blind `sed` patches) discard the real cleanup and break boot.

### 4.2 station2 — `/etc/systemd/system/deca-ns.service`

```ini
[Unit]
Description=Setup CE-B Network Namespace
After=systemd-networkd.service network-online.target
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=2
ExecStartPre=/bin/bash -c "ip link del veth-pe-ceb 2>/dev/null; ip link del veth-pe-ce2 2>/dev/null; ip netns del ce-2 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-b 2>/dev/null; ip netns list | grep -q \"^ce-b\" || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "ip netns add ce-b && ip link add veth-pe-ceb type veth peer name veth-ceb-pe && ip link set veth-ceb-pe netns ce-b && ip link set veth-pe-ceb master vrf-mission && ip addr add 10.10.2.2/30 dev veth-pe-ceb && ip link set veth-pe-ceb up && ip netns exec ce-b ip addr add 10.10.2.1/30 dev veth-ceb-pe && ip netns exec ce-b ip link set veth-ceb-pe up && ip netns exec ce-b ip link set lo up && ip netns exec ce-b ip addr add 10.100.2.1/32 dev lo && ip netns exec ce-b ip route add default via 10.10.2.2 && ip rule add to 10.100.2.1/32 lookup 100 && ip rule add to 10.10.2.0/30 lookup 100 && ip netns exec ce-b sysctl -w net.ipv4.conf.veth-ceb-pe.forwarding=1 && ip netns exec ce-b iptables -F && ip netns exec ce-b iptables -P INPUT ACCEPT && ip netns exec ce-b iptables -P FORWARD ACCEPT && ip netns exec ce-b iperf3 -s -D"
ExecStop=/bin/bash -c "ip netns del ce-b 2>/dev/null; ip link del veth-pe-ceb 2>/dev/null; true"

[Install]
WantedBy=multi-user.target
```

### 4.3 FRR / strongSwan drop-ins (PE1 + PE2)

`/etc/systemd/system/frr.service.d/override.conf` and  
`/etc/systemd/system/strongswan-starter.service.d/override.conf`:

```ini
[Unit]
After=deca-ns.service
Requires=deca-ns.service
```

### 4.4 Watchdog — `/etc/systemd/system/deca-watchdog.service`

```ini
[Unit]
Description=DECA Post-Boot Self-Healing Watchdog
After=frr.service network-online.target deca-ns.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 60
ExecStart=/usr/local/sbin/deca-watchdog.sh

[Install]
WantedBy=multi-user.target
```

(On station3, `After=` omits `deca-ns.service`; script only heals FRR + Telegraf.)

### 4.5 Watchdog script — PE `/usr/local/sbin/deca-watchdog.sh`

```bash
#!/bin/bash
set -e
systemctl reset-failed
systemctl is-active --quiet deca-ns.service 2>/dev/null || systemctl restart deca-ns.service 2>/dev/null || true
sleep 2
systemctl is-active --quiet frr || systemctl restart frr
systemctl is-active --quiet strongswan-starter 2>/dev/null || systemctl restart strongswan-starter 2>/dev/null || true
systemctl is-active --quiet telegraf || systemctl restart telegraf
IP=$(ip -4 -br addr show eth0 2>/dev/null | awk '{print $3}' | cut -d/ -f1)
case "$IP" in
  192.168.50.10)
    vtysh -c "configure terminal" -c "vrf vrf-mission" \
      -c "ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default" \
      -c "ip route 10.10.2.0/30 192.168.50.20 nexthop-vrf default" \
      -c "exit" -c "exit" -c "write" >/dev/null 2>&1 || true
    ;;
  192.168.50.20)
    vtysh -c "configure terminal" -c "vrf vrf-mission" \
      -c "ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default" \
      -c "ip route 10.10.1.0/30 192.168.50.10 nexthop-vrf default" \
      -c "exit" -c "exit" -c "write" >/dev/null 2>&1 || true
    ;;
esac
```

**Why `systemctl reset-failed` every boot:** a June-era `deca-ns` / `strongswan` dependency failure can stick in systemd state and silently block IPsec on later boots even when units look “fine.”

---

## 5. VRF CE static safety-net (VPN dataplane)

When BGP VPNv4 shows **0 prefixes** / unicast **NoNeg**, IPsec can still be ESTABLISHED while CE ping fails. Fix: VRF routes via underlay LAN + IPsec policy (`nexthop-vrf default`).

**station1 (PE1):**

```bash
sudo vtysh -c "configure terminal" -c "vrf vrf-mission" \
  -c "ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default" \
  -c "ip route 10.10.2.0/30 192.168.50.20 nexthop-vrf default" \
  -c "exit" -c "exit" -c "write"
```

**station2 (PE2):**

```bash
sudo vtysh -c "configure terminal" -c "vrf vrf-mission" \
  -c "ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default" \
  -c "ip route 10.10.1.0/30 192.168.50.10 nexthop-vrf default" \
  -c "exit" -c "exit" -c "write"
```

FRR 10.x: persist with **`write`**, not `write memory`.

Verify:

```bash
ssh station1 'sudo vtysh -c "show ip route vrf vrf-mission"'
ssh station1 'sudo ip netns exec ce-a ping -c 3 10.100.2.1'
ssh station1 'sudo ipsec status'   # exactly one ESTABLISHED preferred
```

---

## 6. Laptop Prometheus

`/etc/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: "deca_edge_nodes"
    static_configs:
      - targets: ["192.168.50.10:9273", "192.168.50.20:9273"]

  - job_name: "deca_core_router"
    static_configs:
      - targets: ["192.168.50.30:9273"]
```

Telegraf on Pis uses `[[outputs.prometheus_client]]` with `metric_version = 2` on port **9273**.

### Known failure: `lastError=out of bounds` while `:9273` curls OK

Usually poisoned TSDB after a clock jump. Wipe + **correct ownership** (service `User=prometheus`):

```bash
sudo systemctl stop prometheus
sudo rm -rf /var/lib/prometheus/metrics2/*
sudo mkdir -p /var/lib/prometheus/metrics2
sudo chown -R prometheus:prometheus /var/lib/prometheus/metrics2
sudo chmod 0755 /var/lib/prometheus/metrics2
sudo systemctl reset-failed prometheus
sudo systemctl start prometheus
curl -s localhost:9090/-/ready
curl -s localhost:9090/api/v1/targets
```

If owned by `nobody`, Prometheus panics: `queries.active: permission denied`.

---

## 7. Hostnames

Telegraf tags `host=` from hostname. station2 historically stuck as `ubuntu`.

```bash
sudo hostnamectl set-hostname station1   # on .10
sudo hostnamectl set-hostname station2   # on .20
sudo hostnamectl set-hostname station3   # on .30
sudo systemctl restart telegraf
```

(Deploy script does this automatically.)

---

## 8. Verify (expected green)

```bash
bash ~/deca_diagnostic.sh
```

| Step | Expect |
| --- | --- |
| [1/8] L3 | All three UPS |
| [2/8] NTP | chrony tracking OK |
| [3/8] OSPF | Full neighbors |
| [4/8] BGP | Peer uptime (may still show NoNeg on ipv4 unicast; VPN path uses VRF statics) |
| [5/8] LDP | ACTIVE & POPULATED |
| [6/8] IPsec | one `deca-sdwan` ESTABLISHED |
| [7/8] VPN | `VPN Path time=…` to `10.100.2.1` |
| [8/8] Prom | `3 / 3` |

Helpers:

| Script | Role |
| --- | --- |
| `scripts/deca_deploy_stations.sh` | Full plug-and-play |
| `scripts/deca_heal_telemetry.sh` | Quick ns / IPsec / Telegraf restart |
| `scripts/deca_fix_prom_vpn.sh` | Prom TSDB wipe + VRF statics |
| `scripts/deca_debug_vpn_prom.sh` | Deep debug |

---

## 9. Campaign note

Do **not** run laptop `~/run_traffic.sh` during `deca_fault_campaign.py` — it fights eth0 baseline iperf on the VPN path. Use campaign traffic only.

Fault campaign SSH targets: `station1@192.168.50.10`, `station2@192.168.50.20`, `station3@192.168.50.30` (`scripts/deca_fault_campaign.py`).

---

## 10. Related docs

- Architecture / ML: [`what_is_this.md`](what_is_this.md)
- Data generation: [`DATA_GEN.md`](DATA_GEN.md)
- Prior failure log (duplicates, MOBIKE, DNS): `~/deca-workspace/troubleshooting.md` (if present)
- Model blueprint: [`DECA_Model_Development_Blueprint.md`](DECA_Model_Development_Blueprint.md)

## 11. Breakdown

If validation breaks at **stage 6** (IPsec / VPN path), redeploy then re-check:

```bash
bash ~/deca-isro/scripts/deca_deploy_stations.sh
bash ~/deca_diagnostic.sh
```

### IP addresses inside `deca_deploy_stations.sh`

Lab LAN form: `192.168.50.x`

| Station | Role | `x` | Address |
| --- | --- | ---: | --- |
| `station1` | PE1 | **10** | `192.168.50.10` |
| `station2` | PE2 | **20** | `192.168.50.20` |
| `station3` | CORE | **30** | `192.168.50.30` |
| laptop | management | **1** | `192.168.50.1` |

The deploy script SSHs to `station1` / `station2` / `station3`, then branches VRF safety-net routes by reading each PE’s eth0 address:

```bash
# pattern inside the watchdog / vtysh blocks
IP=$(ip -4 -br addr show eth0 | awk '{print $3}' | cut -d/ -f1)
case "$IP" in
  192.168.50.10)  # PE1 — peer is x=20
      vtysh ... "ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default" ...
      ;;
  192.168.50.20)  # PE2 — peer is x=10
      vtysh ... "ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default" ...
      ;;
esac
```

VPN check target (CE-B loopback): `10.100.2.1` (ping from `ce-a` on PE1).
