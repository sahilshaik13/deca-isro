#!/usr/bin/env python3
"""One-off: remove the stray zebra-detached `router bgp 65001 vrf ADMIN`
FRR stanza left on station2 by the pre-fix `inject_vrf_leakage()` (see
docs/TIER5_VRF_ROUTE_COUNT.md §0). Idempotent — no-ops if already clean.
"""
from __future__ import annotations

import subprocess

PE2_SSH = "station2@192.168.50.20"


def run_ssh(target: str, command: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["ssh", "-T", target, command], capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0, (result.stdout + result.stderr)


def main() -> None:
    ok, out = run_ssh(PE2_SSH, "sudo vtysh -c 'show running-config'")
    if not ok:
        print("FAIL: could not read running-config on station2")
        print(out)
        return

    if "router bgp 65001 vrf ADMIN" not in out:
        print("Already clean: no stray 'vrf ADMIN' bgp instance on station2.")
        return

    print("Found stray 'router bgp 65001 vrf ADMIN' stanza — removing.")
    ok, out = run_ssh(
        PE2_SSH,
        "sudo vtysh -c 'conf t' -c 'no router bgp 65001 vrf ADMIN' -c 'end'",
    )
    print(out.strip())

    ok, out = run_ssh(PE2_SSH, "sudo vtysh -c 'show running-config'")
    if "router bgp 65001 vrf ADMIN" in out:
        print("FAIL: stanza still present after removal attempt.")
    else:
        print("PASS: stray 'vrf ADMIN' bgp instance removed from station2.")


if __name__ == "__main__":
    main()
