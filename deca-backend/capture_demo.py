"""NOC click-to-Wireshark: start capture on a topology link (Pi or GNS3).

GNS3: GNS3 server /links/{id}/start_capture → pcap under Shaik's project captures.
Pi: ssh tcpdump on gre-te-core / eth0 → pcap under Shaik's gns3/captures/pi/.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config
import fabric as fabric_mod

GNS3_API = os.environ.get("DECA_GNS3_API", "http://127.0.0.1:3080/v2")
GNS3_AUTH = os.environ.get("DECA_GNS3_AUTH", "admin:admin")
GNS3_PROJECT = os.environ.get("DECA_GNS3_PROJECT", "DECA")
WIRESHARK = os.environ.get("DECA_WIRESHARK", "/usr/bin/wireshark")
CAPTURE_ROOT = Path(
    os.environ.get(
        "DECA_CAPTURE_ROOT",
        "/media/brain/Shaik's/gns3/captures",
    )
)

STATUS_PATH = Path(
    os.environ.get(
        "DECA_CAPTURE_STATUS",
        str(config.REPO_ROOT / "data" / "deca" / "capture_demo_status.json"),
    )
)

# layout node id → GNS3 canvas name
GNS3_NAME = {
    "pe1": "PE1",
    "pe2": "PE2",
    "pe3": "PE3",
    "core": "CORE-N",
    "core-n": "CORE-N",
    "core-s": "CORE-S",
    "nrsc": "CE-NRSC",
    "mauritius": "CE-Mauritius",
    "sac": "CE-SAC",
    "mcf": "CE-MCF",
    "shadnagar": "CE-Shadnagar",
    "istrac": "CE-ISTRAC",
    "hq": "CE-ISRO-HQ",
    "bhopal": "CE-Bhopal",
    "iperf-a": "IPERF-A",
    "iperf-b": "IPERF-B",
}

# layout link id → Pi tcpdump target
PI_TAPS: dict[str, dict[str, str]] = {
    "gre-pe1-core": {"host": "station1", "iface": "gre-te-core", "label": "PE1↔CORE gre-te"},
    "gre-core-pe2": {"host": "station2", "iface": "gre-te-core", "label": "CORE↔PE2 gre-te"},
    "eth0-backup": {"host": "station1", "iface": "eth0", "label": "PE1 eth0 backup"},
    "ipsec": {"host": "station1", "iface": "eth0", "label": "IPsec/eth0 (ESP)"},
    "ce-nrsc-pe1": {"host": "station1", "iface": "veth-pe-cea", "label": "NRSC attach"},
    "ce-mau-pe1": {"host": "station1", "iface": "veth-pe-cem", "label": "Mauritius attach"},
    "ce-sac-pe2": {"host": "station2", "iface": "veth-pe-ceb", "label": "SAC attach"},
    "ce-mcf-pe2": {"host": "station2", "iface": "veth-pe-cemcf", "label": "MCF attach"},
}

_lock = threading.Lock()
_pi_procs: dict[str, subprocess.Popen] = {}


def _default() -> dict[str, Any]:
    return {
        "active": [],
        "last": None,
        "message": "idle — click a topology link to open Wireshark",
    }


def _read() -> dict[str, Any]:
    if not STATUS_PATH.is_file():
        return _default()
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        base = _default()
        base.update(data)
        return base
    except (OSError, json.JSONDecodeError):
        return _default()


def _write(data: dict[str, Any]) -> dict[str, Any]:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def status() -> dict[str, Any]:
    with _lock:
        st = _read()
        active = fabric_mod.get_active()
        st["active_fabric"] = active
        # Preserve capture fabric from last open; filter active list to current fabric
        started = st.get("fabric") or active
        st["fabric"] = started
        active_caps = [
            a
            for a in (st.get("active") or [])
            if str(a.get("fabric") or started) == active
        ]
        st["active"] = active_caps
        st["wireshark"] = WIRESHARK if Path(WIRESHARK).is_file() else None
        st["capture_root"] = str(CAPTURE_ROOT)
        return st


def _gns3_req(method: str, path: str, body: dict | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": "Basic " + base64.b64encode(GNS3_AUTH.encode()).decode()}
    if body is not None:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(
        f"{GNS3_API}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"GNS3 {method} {path} → {e.code}: {err[:300]}") from e


def _gns3_project_id() -> str:
    for p in _gns3_req("GET", "/projects") or []:
        if p.get("name") == GNS3_PROJECT:
            if p.get("status") != "opened":
                _gns3_req("POST", f"/projects/{p['project_id']}/open")
            return p["project_id"]
    raise RuntimeError(f"GNS3 project {GNS3_PROJECT!r} not found")


def _launch_wireshark(pcap: Path) -> None:
    """Open Wireshark on a (possibly still-growing) pcap.

    Do NOT pass ``-k`` with ``-r`` — Wireshark exits immediately with:
    \"You can't specify both a live capture and a capture file to be read.\"
    GNS3's own reader uses ``tail | wireshark -k -i -`` for live follow.
    """
    if not Path(WIRESHARK).is_file():
        raise RuntimeError(f"wireshark not found at {WIRESHARK}")

    # Wait briefly for GNS3/tcpdump to create the file
    for _ in range(20):
        if pcap.is_file() and pcap.stat().st_size >= 24:
            break
        time.sleep(0.15)
    if not pcap.is_file():
        raise RuntimeError(f"pcap not ready: {pcap}")

    env = os.environ.copy()
    # Prefer the session display (Wayland/Xwayland often :0 or :1)
    if not env.get("DISPLAY"):
        env["DISPLAY"] = os.environ.get("GNOME_SETUP_DISPLAY") or ":0"
    if not env.get("XAUTHORITY"):
        for cand in (
            Path(f"/run/user/{os.getuid()}/gdm/Xauthority"),
            Path.home() / ".Xauthority",
        ):
            if cand.is_file():
                env["XAUTHORITY"] = str(cand)
                break
        else:
            # mutter Xwayland cookie (name varies)
            run = Path(f"/run/user/{os.getuid()}")
            mutters = sorted(run.glob(".mutter-Xwaylandauth*"))
            if mutters:
                env["XAUTHORITY"] = str(mutters[0])

    log = CAPTURE_ROOT / "wireshark_launch.log"
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    log_f = open(log, "ab", buffering=0)

    # Live follow growing capture (same idea as GNS3 packet_capture_reader_command)
    cmd = (
        f'tail -F -c +0 -- "{pcap}" 2>/dev/null '
        f'| "{WIRESHARK}" -k -i - '
        f'-o "gui.window_title:{pcap.name}" '
        f'--capture-comment "DECA NOC {pcap.name}"'
    )
    proc = subprocess.Popen(
        ["bash", "-lc", cmd],
        env=env,
        stdout=log_f,
        stderr=log_f,
        start_new_session=True,
    )
    time.sleep(0.4)
    if proc.poll() is not None:
        # Fallback: open static read (no live follow)
        proc2 = subprocess.Popen(
            [WIRESHARK, "-r", str(pcap)],
            env=env,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
        )
        time.sleep(0.4)
        if proc2.poll() is not None:
            raise RuntimeError(
                f"Wireshark exited immediately — see {log} (DISPLAY={env.get('DISPLAY')})"
            )



def _open_gns3_link(link_id: str, from_id: str, to_id: str) -> dict[str, Any]:
    a = GNS3_NAME.get(from_id, from_id)
    b = GNS3_NAME.get(to_id, to_id)
    want = tuple(sorted([a, b]))
    pid = _gns3_project_id()
    nodes = {n["node_id"]: n["name"] for n in _gns3_req("GET", f"/projects/{pid}/nodes") or []}
    match = None
    for L in _gns3_req("GET", f"/projects/{pid}/links") or []:
        ends = tuple(sorted(nodes.get(x["node_id"], "?") for x in L.get("nodes") or []))
        if ends == want:
            match = L
            break
    if not match:
        raise RuntimeError(f"no GNS3 link for {a} ↔ {b}")

    lid = match["link_id"]
    if not match.get("capturing"):
        fname = f"noc_{a}_{b}.pcap"
        _gns3_req(
            "POST",
            f"/projects/{pid}/links/{lid}/start_capture",
            {"data_link_type": "DLT_EN10MB", "capture_file_name": fname},
        )
        time.sleep(0.6)
        # refresh
        for L in _gns3_req("GET", f"/projects/{pid}/links") or []:
            if L.get("link_id") == lid:
                match = L
                break

    pcap_path = match.get("capture_file_path") or ""
    if not pcap_path:
        # fallback known project captures dir
        cap_dir = (
            Path(os.environ.get("DECA_GNS3_ROOT", "/media/brain/Shaik's/gns3"))
            / "projects"
            / GNS3_PROJECT
            / "project-files"
            / "captures"
        )
        # newest matching
        cands = sorted(cap_dir.glob(f"*{a}*{b}*.pcap"), key=lambda p: p.stat().st_mtime, reverse=True)
        cands += sorted(cap_dir.glob(f"*{b}*{a}*.pcap"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            raise RuntimeError("capture started but pcap path not found yet — retry click")
        pcap_path = str(cands[0])

    pcap = Path(pcap_path)
    _launch_wireshark(pcap)
    return {
        "fabric": "gns3",
        "link_id": link_id,
        "ends": [a, b],
        "pcap": str(pcap),
        "capturing": True,
        "message": f"Wireshark ← {a} ↔ {b}",
    }


def _open_pi_link(link_id: str) -> dict[str, Any]:
    tap = PI_TAPS.get(link_id)
    if not tap:
        raise RuntimeError(
            f"link {link_id!r} is not captureable on Pi "
            "(try gre-pe1-core, gre-core-pe2, eth0-backup, ipsec)"
        )
    host, iface, label = tap["host"], tap["iface"], tap["label"]
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    pi_dir = CAPTURE_ROOT / "pi"
    pi_dir.mkdir(parents=True, exist_ok=True)
    pcap = pi_dir / f"{link_id}_{int(time.time())}.pcap"

    # Stop previous capture on same link
    old = _pi_procs.pop(link_id, None)
    if old and old.poll() is None:
        try:
            old.terminate()
        except OSError:
            pass

    # Remote tcpdump → local pcap on Shaik's (not root /tmp)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=6",
        host,
        f"sudo tcpdump -i {iface} -U -w - 2>/dev/null",
    ]
    out = open(pcap, "wb")
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL, start_new_session=True)
    _pi_procs[link_id] = proc
    time.sleep(0.8)
    if proc.poll() is not None:
        out.close()
        raise RuntimeError(
            f"tcpdump failed on {host}:{iface} — check SSH/sudo and iface exists"
        )
    _launch_wireshark(pcap)
    return {
        "fabric": "pi",
        "link_id": link_id,
        "host": host,
        "iface": iface,
        "pcap": str(pcap),
        "label": label,
        "capturing": True,
        "message": f"Wireshark ← {label} ({host}:{iface})",
    }


def open_link(
    link_id: str,
    *,
    from_id: str = "",
    to_id: str = "",
    fabric: str | None = None,
) -> dict[str, Any]:
    fab = (fabric or fabric_mod.get_active()).strip().lower()
    with _lock:
        try:
            if fab == "gns3":
                if not from_id or not to_id:
                    # derive from layout
                    import topology as topology_mod

                    lay = topology_mod.layout("gns3")
                    for lnk in lay.get("links") or []:
                        if lnk.get("id") == link_id:
                            from_id = lnk.get("from") or from_id
                            to_id = lnk.get("to") or to_id
                            break
                result = _open_gns3_link(link_id, from_id, to_id)
            else:
                result = _open_pi_link(link_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "fabric": fab}

        st = _read()
        active = [a for a in (st.get("active") or []) if a.get("link_id") != link_id]
        active.append({**result, "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        st["active"] = active[-12:]
        st["last"] = result
        st["message"] = result.get("message") or "opened"
        _write(st)
        return {"ok": True, **result, "status": st}


def stop_link(link_id: str | None = None) -> dict[str, Any]:
    """Stop Pi tcpdump processes; GNS3 captures left running (GNS3 owns them)."""
    with _lock:
        stopped = []
        if link_id:
            proc = _pi_procs.pop(link_id, None)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
                stopped.append(link_id)
        else:
            for lid, proc in list(_pi_procs.items()):
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    stopped.append(lid)
            _pi_procs.clear()
        st = _read()
        st["message"] = f"stopped {stopped or 'none'}"
        _write(st)
        return {"ok": True, "stopped": stopped, "status": st}
