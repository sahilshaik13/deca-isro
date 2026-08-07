"""Multi-terminal session manager for the orchestrator dashboard.

Monitor sessions (read-only): station1/2/3 via SSH status loops, prometheus via local watch.
Interactive sessions: local bash (brain) or ssh -tt to a station.
Simulation log lines matching ``→ stationN ::`` are injected into that station's monitor.
"""
from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import config

ALLOWED_TARGETS = frozenset({"brain", "station1", "station2", "station3"})
MONITOR_STATIONS = ("station1", "station2", "station3")
MAX_INTERACTIVE = 6
HISTORY_BYTES = 64 * 1024
SIM_ACTIVITY_RE = re.compile(r"→\s*(station[123])\s*::")

SIM_LOG_PATH = Path(
    os.environ.get("DECA_SIM_LOG", str(config.REPO_ROOT / "data" / "deca" / "simulation.log"))
).resolve()

Subscriber = Callable[[bytes], None]


@dataclass
class TerminalSession:
    id: str
    label: str
    target: str
    mode: str  # monitor | interactive
    readonly: bool
    status: str = "starting"
    cmd_summary: str = ""
    created_at: float = field(default_factory=time.time)
    _history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_BYTES))
    _subscribers: list[Subscriber] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _master_fd: Optional[int] = None
    _proc: Optional[subprocess.Popen] = None
    _reader_thread: Optional[threading.Thread] = None
    _stop: threading.Event = field(default_factory=threading.Event)

    def meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "target": self.target,
            "mode": self.mode,
            "readonly": self.readonly,
            "status": self.status,
            "cmd_summary": self.cmd_summary,
            "created_at": self.created_at,
        }

    def subscribe(self, cb: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(cb)
            # Replay history as a single chunk
            if self._history:
                cb(bytes(self._history))

    def unsubscribe(self, cb: Subscriber) -> None:
        with self._lock:
            try:
                self._subscribers.remove(cb)
            except ValueError:
                pass

    def _append_history(self, data: bytes) -> None:
        for b in data:
            self._history.append(b)

    def broadcast(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._append_history(data)
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(data)
            except Exception:  # noqa: BLE001
                pass

    def write_input(self, data: bytes) -> bool:
        if self.readonly or self._master_fd is None:
            return False
        try:
            os.write(self._master_fd, data)
            return True
        except OSError:
            return False

    def resize(self, rows: int, cols: int) -> None:
        if self._master_fd is None:
            return
        try:
            import fcntl
            import struct
            import termios

            winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        self._stop.set()
        self.status = "closed"
        proc = self._proc
        fd = self._master_fd
        self._master_fd = None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if self._reader_thread and self._reader_thread.is_alive() and threading.current_thread() is not self._reader_thread:
            self._reader_thread.join(timeout=1.5)


class TerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()
        self._sim_tail_thread: Optional[threading.Thread] = None
        self._prom_thread: Optional[threading.Thread] = None
        self._started = False
        self._stop = threading.Event()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for host in MONITOR_STATIONS:
            self._spawn_station_monitor(host)
        self._spawn_prometheus_monitor()
        self._spawn_pipeline_monitors()
        self._sim_tail_thread = threading.Thread(
            target=self._tail_sim_log, name="term-sim-tail", daemon=True
        )
        self._sim_tail_thread.start()

    def _spawn_pipeline_monitors(self) -> None:
        watch = str(config.REPO_ROOT / "scripts" / "deca_watch.sh")
        tabs = [
            ("m-pipe-inject", "1. Inject", "tail -F data/deca/pipeline_inject.log"),
            ("m-pipe-telem", "2. Telemetry", "tail -F data/deca/pipeline_telemetry.log"),
            ("m-pipe-infer", "3. Inference", "tail -F data/deca/pipeline_inference.log"),
            ("m-pipe-copilot", "4. Copilot", "tail -F data/deca/pipeline_copilot.log"),
            ("m-pipe-decide", "5. Decide", "tail -F data/deca/pipeline_decide.log"),
            # Backend-owned live API watcher (not a frontend page).
            (
                "m-pipe-watch",
                "6. Live Watch",
                f"bash {watch}",
            ),
        ]
        for sid, label, cmd_str in tabs:
            session = TerminalSession(
                id=sid,
                label=label,
                target="pipeline",
                mode="monitor",
                readonly=True,
                status="starting",
                cmd_summary=cmd_str,
            )
            self._register(session)
            if sid == "m-pipe-watch":
                cmd = ["bash", watch]
            else:
                log_file = cmd_str.split()[-1]
                cmd = [
                    "bash",
                    "-c",
                    f"mkdir -p $(dirname {log_file}) && touch {log_file} && {cmd_str}",
                ]
            self._attach_pty(session, cmd, cwd=str(config.REPO_ROOT))

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            s.close()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._sessions.values())
        # Monitors first, then interactive by created_at
        items.sort(key=lambda s: (0 if s.mode == "monitor" else 1, s.created_at, s.id))
        return [s.meta() for s in items]

    def get(self, session_id: str) -> Optional[TerminalSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def create_interactive(self, target: str) -> TerminalSession:
        target = (target or "").strip().lower()
        if target not in ALLOWED_TARGETS:
            raise ValueError(f"invalid target (allowed: {sorted(ALLOWED_TARGETS)})")
        with self._lock:
            interactive = [s for s in self._sessions.values() if s.mode == "interactive"]
            if len(interactive) >= MAX_INTERACTIVE:
                raise RuntimeError(f"max interactive terminals ({MAX_INTERACTIVE}) reached")
            sid = f"i-{uuid.uuid4().hex[:10]}"
            label = f"{target} (interactive)"
            session = TerminalSession(
                id=sid,
                label=label,
                target=target,
                mode="interactive",
                readonly=False,
                status="starting",
            )
            self._sessions[sid] = session

        if target == "brain":
            cmd = ["bash", "-l"]
            session.cmd_summary = "bash -l (brain)"
            self._attach_pty(session, cmd, cwd=str(config.REPO_ROOT))
        else:
            cmd = [
                "ssh",
                "-tt",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                target,
            ]
            session.cmd_summary = f"ssh -tt {target}"
            self._attach_pty(session, cmd, cwd=str(config.REPO_ROOT))
        return session

    def delete_interactive(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.mode != "interactive":
                raise PermissionError("monitor sessions cannot be deleted")
            del self._sessions[session_id]
        session.close()
        return True

    def _register(self, session: TerminalSession) -> None:
        with self._lock:
            self._sessions[session.id] = session

    def _spawn_station_monitor(self, host: str) -> None:
        sid = f"m-{host}"
        # No full-screen clear — keeps [sim] activity lines visible in scrollback.
        remote = (
            "echo \"=== ${HOSTNAME:-$(hostname)} monitor (read-only) ===\"; "
            "date; uptime; "
            "ip -br link 2>/dev/null | head -n 16 || true; "
            "echo; echo 'Listening for lab sim activity on this host...'; "
            "echo 'Use Add Terminal for an interactive shell.'; "
            "echo; "
            "i=0; while true; do "
            "i=$((i+1)); "
            "if [ $((i % 6)) -eq 0 ]; then "
            "echo \"[heartbeat $(date +%H:%M:%S)] $(uptime -p 2>/dev/null || uptime)\"; "
            "fi; "
            "sleep 5; "
            "done"
        )
        cmd = [
            "ssh",
            "-tt",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ServerAliveInterval=15",
            host,
            remote,
        ]
        session = TerminalSession(
            id=sid,
            label=host,
            target=host,
            mode="monitor",
            readonly=True,
            status="starting",
            cmd_summary=f"ssh -tt {host} (status loop)",
        )
        self._register(session)
        self._attach_pty(session, cmd, cwd=str(config.REPO_ROOT))

    def _spawn_prometheus_monitor(self) -> None:
        sid = "m-prometheus"
        session = TerminalSession(
            id=sid,
            label="prometheus",
            target="prometheus",
            mode="monitor",
            readonly=True,
            status="running",
            cmd_summary=f"watch {config.PROMETHEUS_URL}",
        )
        self._register(session)
        self._prom_thread = threading.Thread(
            target=self._prometheus_loop,
            args=(session,),
            name="term-prom",
            daemon=True,
        )
        self._prom_thread.start()

    def _prometheus_loop(self, session: TerminalSession) -> None:
        base = config.PROMETHEUS_URL.rstrip("/")
        while not self._stop.is_set() and not session._stop.is_set():
            lines = [
                "\033[H\033[2J",
                "=== prometheus monitor (read-only) ===\n",
                f"url: {base}\n",
                f"ts:  {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
            ]
            ready = self._http_get(f"{base}/-/ready", timeout=3)
            lines.append(f"ready: {ready.strip() or '(no response)'}\n")
            healthy = self._http_get(f"{base}/-/healthy", timeout=3)
            lines.append(f"healthy: {healthy.strip() or '(no response)'}\n\n")
            targets_raw = self._http_get(f"{base}/api/v1/targets", timeout=5)
            lines.append(self._format_prom_targets(targets_raw))
            lines.append("\nUse Add Terminal → brain for promtool / curl.\n")
            session.broadcast("".join(lines).encode("utf-8", errors="replace"))
            session.status = "running" if ready else "degraded"
            for _ in range(50):
                if self._stop.is_set() or session._stop.is_set():
                    break
                time.sleep(0.1)
        session.status = "closed"

    @staticmethod
    def _http_get(url: str, timeout: float = 5.0) -> str:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return f"ERROR: {exc}"

    @staticmethod
    def _format_prom_targets(raw: str) -> str:
        if raw.startswith("ERROR:"):
            return raw + "\n"
        try:
            data = json.loads(raw)
            active = data.get("data", {}).get("activeTargets") or []
            if not active:
                return "targets: (none)\n"
            out = ["targets:\n"]
            for t in active[:40]:
                labels = t.get("labels") or {}
                job = labels.get("job", "?")
                instance = labels.get("instance", "?")
                health = t.get("health", "?")
                out.append(f"  [{health}] {job} @ {instance}\n")
            if len(active) > 40:
                out.append(f"  … {len(active) - 40} more\n")
            return "".join(out)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return (raw[:800] + "\n") if raw else "targets: (unreadable)\n"

    def _attach_pty(self, session: TerminalSession, cmd: list[str], cwd: str) -> None:
        try:
            master, slave = pty.openpty()
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            proc = subprocess.Popen(
                cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            os.close(slave)
            session._master_fd = master
            session._proc = proc
            session.status = "running"
            session._reader_thread = threading.Thread(
                target=self._read_pty,
                args=(session,),
                name=f"term-read-{session.id}",
                daemon=True,
            )
            session._reader_thread.start()
        except Exception as exc:  # noqa: BLE001
            session.status = "error"
            session.broadcast(f"\r\n[terminal error] failed to start: {exc}\r\n".encode())

    def _read_pty(self, session: TerminalSession) -> None:
        fd = session._master_fd
        if fd is None:
            return
        try:
            while not session._stop.is_set():
                if session._proc is not None and session._proc.poll() is not None:
                    # Drain remaining
                    try:
                        while True:
                            r, _, _ = select.select([fd], [], [], 0)
                            if not r:
                                break
                            chunk = os.read(fd, 4096)
                            if not chunk:
                                break
                            session.broadcast(chunk)
                    except OSError:
                        pass
                    break
                try:
                    r, _, _ = select.select([fd], [], [], 0.5)
                except (OSError, ValueError):
                    break
                if not r:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                session.broadcast(chunk)
        finally:
            if session.status != "closed":
                session.status = "exited" if session.mode == "interactive" else "disconnected"
            if session.mode == "monitor" and session.target in MONITOR_STATIONS and not self._stop.is_set():
                # Auto-reconnect station monitors after a short pause
                session.broadcast(b"\r\n[monitor] reconnecting in 3s...\r\n")
                time.sleep(3)
                if not self._stop.is_set() and not session._stop.is_set():
                    self._reconnect_station_monitor(session)

    def _reconnect_station_monitor(self, session: TerminalSession) -> None:
        if session._master_fd is not None:
            try:
                os.close(session._master_fd)
            except OSError:
                pass
            session._master_fd = None
        session._proc = None
        session._stop.clear()
        host = session.target
        remote = (
            "echo \"=== ${HOSTNAME:-$(hostname)} monitor (read-only) ===\"; "
            "date; uptime; "
            "ip -br link 2>/dev/null | head -n 16 || true; "
            "echo; echo 'Listening for lab sim activity on this host...'; "
            "echo 'Use Add Terminal for an interactive shell.'; "
            "echo; "
            "i=0; while true; do "
            "i=$((i+1)); "
            "if [ $((i % 6)) -eq 0 ]; then "
            "echo \"[heartbeat $(date +%H:%M:%S)] $(uptime -p 2>/dev/null || uptime)\"; "
            "fi; "
            "sleep 5; "
            "done"
        )
        cmd = [
            "ssh",
            "-tt",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ServerAliveInterval=15",
            host,
            remote,
        ]
        self._attach_pty(session, cmd, cwd=str(config.REPO_ROOT))

    def inject_activity(self, host: str, line: str) -> None:
        sid = f"m-{host}"
        session = self.get(sid)
        if session is None:
            return
        msg = f"\r\n\033[33m[sim]\033[0m {line.rstrip()}\r\n"
        session.broadcast(msg.encode("utf-8", errors="replace"))

    def _tail_sim_log(self) -> None:
        path = SIM_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.touch()
        # Start at EOF
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while not self._stop.is_set():
                line = fh.readline()
                if not line:
                    time.sleep(0.4)
                    continue
                m = SIM_ACTIVITY_RE.search(line)
                if m:
                    self.inject_activity(m.group(1), line.strip())


manager = TerminalManager()
