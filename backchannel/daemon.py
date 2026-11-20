"""Background daemon manager for the unified 6-in-1 backchannel Python suite."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .analyzer import iso_now
from .config import get_data_dir, load_config, resolve_omniroute_upstream, resolve_proxy_upstream


def get_daemon_state_path(override_dir: str | Path | None = None) -> Path:
    return get_data_dir(override_dir) / "daemon.json"


def get_daemon_log_path(override_dir: str | Path | None = None) -> Path:
    return get_data_dir(override_dir) / "daemon.log"


def is_pid_alive(pid: int | None) -> bool:
    if not pid or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == 259  # STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _kill_pid(pid: int) -> bool:
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return r.returncode == 0
        except Exception:
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def read_daemon_state(override_dir: str | Path | None = None) -> dict[str, Any] | None:
    path = get_daemon_state_path(override_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_daemon_state(state: dict[str, Any], override_dir: str | Path | None = None) -> None:
    try:
        data_dir = get_data_dir(override_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        get_daemon_state_path(override_dir).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def clear_daemon_state(override_dir: str | Path | None = None) -> None:
    try:
        path = get_daemon_state_path(override_dir)
        if path.exists():
            path.unlink()
    except OSError:
        pass


def probe_json(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def get_daemon_status(override_dir: str | Path | None = None) -> dict[str, Any]:
    cfg = load_config(override_dir)
    saved = read_daemon_state(override_dir) or {}
    dash_port = int(saved.get("dashboardPort") or cfg.get("dashboardPort") or 4242)
    proxy_port = int(saved.get("proxyPort") or cfg.get("proxyPort") or 4243)

    dash_state = probe_json(f"http://127.0.0.1:{dash_port}/api/health", timeout=1.0)
    proxy_health = probe_json(f"http://127.0.0.1:{proxy_port}/_backchannel/health", timeout=1.0)

    pid = saved.get("pid")
    pid_alive = is_pid_alive(pid) if isinstance(pid, int) else False
    running = bool(dash_state and proxy_health)

    return {
        "running": running,
        "pid": pid or (dash_state.get("pid") if dash_state else None),
        "pidAlive": pid_alive,
        "dashboardUp": bool(dash_state),
        "proxyUp": bool(proxy_health),
        "dashboardUrl": f"http://127.0.0.1:{dash_port}",
        "proxyUrl": f"http://127.0.0.1:{proxy_port}",
        "omniProxyUrl": f"http://127.0.0.1:{proxy_port}/omni",
        "upstream": (proxy_health or {}).get("upstream")
        or saved.get("upstream")
        or resolve_proxy_upstream(cfg, proxy_port=proxy_port),
        "omniUpstream": (proxy_health or {}).get("omniUpstream")
        or saved.get("omniUpstream")
        or resolve_omniroute_upstream(cfg, proxy_port=proxy_port),
        "requestsProxied": (proxy_health or {}).get("requestsProxied", 0),
        "requestsCompressed": (proxy_health or {}).get("requestsCompressed", 0),
        "omniRequestsProxied": (proxy_health or {}).get("omniRequestsProxied", 0),
        "omniRequestsCompressed": (proxy_health or {}).get("omniRequestsCompressed", 0),
        "totalSavedTokens": (proxy_health or {}).get("totalSavedTokens", 0),
        "dashboardPort": dash_port,
        "proxyPort": proxy_port,
        "graphDir": saved.get("graphDir"),
        "startedAt": saved.get("startedAt"),
        "logFile": str(get_daemon_log_path(override_dir)),
    }


def start_background_daemon(
    *,
    port: int | None = None,
    proxy_port: int | None = None,
    upstream: str | None = None,
    omni_upstream: str | None = None,
    graph_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    resolved_data_dir = get_data_dir(data_dir)
    cfg = load_config(resolved_data_dir)
    dash_port = int(port or cfg.get("dashboardPort") or 4242)
    px_port = int(proxy_port or cfg.get("proxyPort") or 4243)
    resolved_graph_dir = str(Path(graph_dir or os.getcwd()).resolve())
    resolved_upstream = resolve_proxy_upstream(cfg, proxy_port=px_port, upstream=upstream)
    resolved_omni = resolve_omniroute_upstream(cfg, proxy_port=px_port, omni_upstream=omni_upstream)

    current = get_daemon_status(resolved_data_dir)
    if (
        current["running"]
        and current["dashboardPort"] == dash_port
        and current["proxyPort"] == px_port
        and current["upstream"] == resolved_upstream
        and current["omniUpstream"] == resolved_omni
    ):
        return {**current, "alreadyRunning": True}

    if current.get("pid") and current.get("pidAlive"):
        _kill_pid(int(current["pid"]))
        clear_daemon_state(resolved_data_dir)
        time.sleep(0.35)

    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    log_path = get_daemon_log_path(resolved_data_dir)
    cmd = [
        sys.executable,
        "-m",
        "backchannel",
        "_daemon-worker",
        "--port",
        str(dash_port),
        "--proxy-port",
        str(px_port),
        "--upstream",
        resolved_upstream,
        "--omni-upstream",
        resolved_omni,
        "--graph-dir",
        resolved_graph_dir,
    ]
    if demo:
        cmd.append("--demo")

    env = {**os.environ, "BACKCHANNEL_DATA_DIR": str(resolved_data_dir)}
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    existing_py = env.get("PYTHONPATH", "")
    if pkg_parent not in existing_py.split(os.pathsep):
        env["PYTHONPATH"] = f"{pkg_parent}{os.pathsep}{existing_py}" if existing_py else pkg_parent

    popen_kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "env": env, "cwd": pkg_parent}
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    with log_path.open("a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, **popen_kwargs)

    deadline = time.time() + 8.0
    ready = False
    while time.time() < deadline:
        d = probe_json(f"http://127.0.0.1:{dash_port}/api/health", timeout=0.6)
        p = probe_json(f"http://127.0.0.1:{px_port}/_backchannel/health", timeout=0.6)
        if d and p:
            ready = True
            break
        time.sleep(0.2)

    state = {
        "pid": proc.pid,
        "dashboardPort": dash_port,
        "proxyPort": px_port,
        "upstream": resolved_upstream,
        "omniUpstream": resolved_omni,
        "graphDir": resolved_graph_dir,
        "startedAt": iso_now(),
    }
    write_daemon_state(state, resolved_data_dir)

    if not ready:
        raise RuntimeError(
            f"Background daemon started (pid {proc.pid}) but did not pass health checks within 8s. Check {log_path}"
        )

    return {
        "running": True,
        "alreadyRunning": False,
        "pid": proc.pid,
        "dashboardUp": True,
        "proxyUp": True,
        "dashboardPort": dash_port,
        "proxyPort": px_port,
        "upstream": resolved_upstream,
        "omniUpstream": resolved_omni,
        "dashboardUrl": f"http://127.0.0.1:{dash_port}",
        "proxyUrl": f"http://127.0.0.1:{px_port}",
        "omniProxyUrl": f"http://127.0.0.1:{px_port}/omni",
        "graphDir": resolved_graph_dir,
        "startedAt": state["startedAt"],
        "logFile": str(log_path),
    }


def stop_background_daemon(override_dir: str | Path | None = None) -> dict[str, Any]:
    data_dir = get_data_dir(override_dir)
    saved = read_daemon_state(data_dir)
    stopped = False
    pid = saved.get("pid") if saved else None
    if isinstance(pid, int) and is_pid_alive(pid):
        stopped = _kill_pid(pid)
        deadline = time.time() + 2.5
        while time.time() < deadline and is_pid_alive(pid):
            time.sleep(0.12)
    clear_daemon_state(data_dir)
    return {"stopped": stopped, "pid": pid}
