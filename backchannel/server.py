"""Zero-dependency Python HTTP + SSE Dashboard server for the unified 6-in-1 backchannel suite."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .analyzer import iso_now, summarize_portfolio
from .card import render_share_card_svg
from .compressor import (
    compress_tool_output,
    compute_headroom_summary,
    load_savings_ledger,
    record_compression_saving,
)
from .config import load_config, resolve_omniroute_upstream, resolve_proxy_upstream, save_config
from .demo_data import create_live_simulation_script
from .doc_compress import compress_markdown_text
from .graphify import build_knowledge_graph, load_knowledge_graph, query_knowledge_graph
from .memory import (
    add_memory,
    delete_memory,
    get_seed_memories,
    load_memories,
    search_memories,
    summarize_session_to_memory,
)
from .modes import build_policy_prompt
from .proxy import HeadroomProxyServer
from .repo_audit import run_repo_audit
from .store import BackchannelStore

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = (PLUGIN_ROOT / "ui").resolve()

MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
}

_cli_cache_lock = threading.Lock()
_cli_cache: dict[str, Any] = {
    "installed": False,
    "version": "checking…",
    "pluginEnabled": False,
    "pluginVersion": __version__,
    "mcpTools": 13,
    "checkedAt": 0.0,
}
_cli_probe_running = False


def _refresh_claude_cli_async(on_done: Any = None) -> None:
    global _cli_probe_running
    with _cli_cache_lock:
        if _cli_probe_running:
            return
        _cli_probe_running = True

    def worker() -> None:
        global _cli_probe_running
        info: dict[str, Any]
        try:
            r1 = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=4,
                shell=(os.name == "nt"),
            )
            if r1.returncode != 0 or not r1.stdout.strip():
                info = {
                    "installed": False,
                    "version": "not detected",
                    "pluginEnabled": False,
                    "pluginVersion": __version__,
                    "mcpTools": 13,
                    "checkedAt": time.time(),
                }
            else:
                ver = r1.stdout.strip()
                r2 = subprocess.run(
                    ["claude", "plugin", "list"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    shell=(os.name == "nt"),
                )
                enabled = r2.returncode == 0 and bool(
                    re.search(r"backchannel@backchannel[\s\S]{0,180}enabled", r2.stdout or "", re.I)
                )
                info = {
                    "installed": True,
                    "version": ver,
                    "pluginEnabled": enabled,
                    "pluginVersion": __version__,
                    "mcpTools": 13,
                    "checkedAt": time.time(),
                }
        except Exception:
            info = {
                "installed": False,
                "version": "not detected",
                "pluginEnabled": False,
                "pluginVersion": __version__,
                "mcpTools": 13,
                "checkedAt": time.time(),
            }

        with _cli_cache_lock:
            _cli_cache.update(info)
            _cli_probe_running = False
        if on_done:
            try:
                on_done()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def probe_claude_cli(on_done: Any = None) -> dict[str, Any]:
    with _cli_cache_lock:
        stale = (time.time() - float(_cli_cache.get("checkedAt", 0.0))) > 30.0
        snap = dict(_cli_cache)
    if stale:
        _refresh_claude_cli_async(on_done)
    return snap


class DashboardServer:
    """Managed Dashboard + SSE + In-Process Headroom/OmniRoute Proxy server."""

    def __init__(
        self,
        *,
        store: BackchannelStore | None = None,
        demo: bool = False,
        data_dir: str | Path | None = None,
        claude_projects_dir: str | Path | None = None,
        graph_dir: str | Path | None = None,
    ) -> None:
        self.store = store or BackchannelStore(
            demo=demo, data_dir=data_dir, claude_projects_dir=claude_projects_dir
        )
        self.data_dir = Path(data_dir) if data_dir else self.store.data_dir
        self.active_graph_dir = Path(graph_dir).resolve() if graph_dir else PLUGIN_ROOT
        self.active_graph = load_knowledge_graph(self.active_graph_dir)
        if not self.active_graph:
            try:
                self.active_graph = build_knowledge_graph(self.active_graph_dir, persist=False)
            except Exception:
                self.active_graph = None
        self.active_repo_audit: dict[str, Any] | None = None

        self._lock = threading.Lock()
        self.proxy_instance: HeadroomProxyServer | None = None
        self.proxy_port: int | None = None
        self._sse_clients: set[tuple[queue.Queue[str | None], str]] = set()
        self._sim_stop_event: threading.Event | None = None
        self._sim_state: dict[str, Any] | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0
        self.host: str = "127.0.0.1"

        self.store.on_update(lambda _: self.broadcast("state"))

    def build_payload(self, mode: str = "auto") -> dict[str, Any]:
        result = self.store.get_sessions(mode)
        config = load_config(self.data_dir)
        ledger = load_savings_ledger(self.data_dir, 40)
        headroom = compute_headroom_summary(result["sessions"], ledger, config)
        stored_memories = load_memories(self.data_dir)
        if stored_memories:
            memories = stored_memories
        else:
            now = datetime.now(timezone.utc)
            memories = [
                {
                    **m,
                    "id": f"seed-{i + 1}",
                    "createdAt": (now - timedelta(hours=i + 1)).isoformat().replace("+00:00", "Z"),
                    "tokens": max(1, (len(m["body"]) + 3) // 4),
                    "isSeed": True,
                }
                for i, m in enumerate(get_seed_memories())
            ]

        project_name = result["sessions"][0]["project"] if result["sessions"] else self.active_graph_dir.name
        policy = build_policy_prompt(
            config,
            cwd=self.active_graph_dir,
            project=project_name,
            data_dir=self.data_dir,
            has_local_graph=bool(self.active_graph),
            preview=True,
        )

        with self._lock:
            px = self.proxy_instance
            px_port = self.proxy_port
            sim = self._sim_state
            graph = self.active_graph
            audit = self.active_repo_audit

        if px and px_port:
            proxy_payload = {
                "running": True,
                "port": px_port,
                "url": f"http://127.0.0.1:{px_port}",
                "omniUrl": f"http://127.0.0.1:{px_port}/omni",
                **px.stats,
            }
        else:
            default_px_port = int(config.get("proxyPort") or 4243)
            proxy_payload = {
                "running": False,
                "port": default_px_port,
                "url": f"http://127.0.0.1:{default_px_port}",
                "omniUrl": f"http://127.0.0.1:{default_px_port}/omni",
                "upstream": resolve_proxy_upstream(config),
                "omniUpstream": resolve_omniroute_upstream(config),
                "requestsProxied": 0,
                "requestsCompressed": 0,
                "omniRequestsProxied": 0,
                "omniRequestsCompressed": 0,
                "totalSavedTokens": 0,
            }

        graph_payload = (
            {
                "project": graph["project"],
                "rootDir": graph["rootDir"],
                "builtAt": graph["builtAt"],
                "stats": graph["stats"],
                "communities": graph["communities"],
                "hubs": graph["hubs"],
                "nodes": graph["nodes"][:60],
                "edges": graph["edges"][:120],
            }
            if graph
            else None
        )

        sim_payload = (
            {
                "active": True,
                "sessionId": sim["session"]["id"],
                "step": sim["index"],
                "total": len(sim["steps"]),
            }
            if sim
            else {"active": False, "sessionId": None, "step": 0, "total": 0}
        )

        return {
            "version": __version__,
            "activeSource": result["activeSource"],
            "counts": result["counts"],
            "sessions": result["sessions"],
            "portfolio": summarize_portfolio(result["sessions"]),
            "config": config,
            "policy": policy,
            "headroom": headroom,
            "proxy": proxy_payload,
            "graph": graph_payload,
            "repoAudit": audit,
            "memories": {
                "count": len(memories),
                "isSeedOnly": len(stored_memories) == 0,
                "items": memories[:50],
            },
            "claudeCli": probe_claude_cli(lambda: self.broadcast("state")),
            "diagnostics": self.store.get_diagnostics(),
            "simulation": sim_payload,
            "updatedAt": iso_now(),
        }

    def broadcast(self, event_type: str = "state") -> None:
        with self._lock:
            clients = list(self._sse_clients)
        if not clients:
            return
        cache: dict[str, str] = {}
        for q, mode in clients:
            if mode not in cache:
                cache[mode] = f"event: {event_type}\ndata: {json.dumps(self.build_payload(mode))}\n\n"
            try:
                q.put_nowait(cache[mode])
            except queue.Full:
                pass

    def start_proxy(
        self,
        requested_port: int | None = None,
        upstream: str | None = None,
        omni_upstream: str | None = None,
    ) -> dict[str, Any]:
        self.stop_proxy()
        cfg = load_config(self.data_dir)
        port = int(requested_port if requested_port is not None else (cfg.get("proxyPort") or 4243))
        inst = HeadroomProxyServer(
            port=port,
            upstream=upstream,
            omni_upstream=omni_upstream,
            data_dir=self.data_dir,
            on_saving=lambda _: self.broadcast("state"),
        )
        bound_port = inst.start()
        with self._lock:
            self.proxy_instance = inst
            self.proxy_port = bound_port
        self.broadcast("state")
        return {
            "port": bound_port,
            "url": f"http://127.0.0.1:{bound_port}",
            "omniUrl": f"http://127.0.0.1:{bound_port}/omni",
            "upstream": inst.upstream_str,
            "omniUpstream": inst.omni_str,
        }

    def stop_proxy(self) -> bool:
        with self._lock:
            inst = self.proxy_instance
            self.proxy_instance = None
            self.proxy_port = None
        if not inst:
            return False
        inst.stop()
        self.broadcast("state")
        return True

    def stop_simulation(self) -> None:
        with self._lock:
            ev = self._sim_stop_event
            self._sim_stop_event = None
            sim = self._sim_state
            self._sim_state = None
        if ev:
            ev.set()
        if sim:
            sess = dict(sim["session"])
            sess["isLive"] = False
            sess["agents"] = [{**a, "status": "done"} for a in sess["agents"]]
            self.store.upsert_simulated_session(sess)
            self.broadcast("state")

    def start_simulation(self, interval_sec: float = 1.75) -> str:
        self.stop_simulation()
        script = create_live_simulation_script()
        base_dt = datetime.now(timezone.utc)
        session = {
            "id": script["id"],
            "title": script["title"],
            "project": script["project"],
            "source": "demo",
            "isLive": True,
            "startedAt": base_dt.isoformat().replace("+00:00", "Z"),
            "agents": [{**a, "status": "waiting"} for a in script["agents"]],
            "messages": [],
        }
        stop_ev = threading.Event()
        sim_state = {"session": session, "steps": script["steps"], "index": 0, "baseDt": base_dt}
        with self._lock:
            self._sim_stop_event = stop_ev
            self._sim_state = sim_state

        def tick() -> bool:
            with self._lock:
                st = self._sim_state
                if not st or st["index"] >= len(st["steps"]):
                    return False
                step_idx = st["index"]
                step = st["steps"][step_idx]
                st["index"] += 1
                offset_sec = 0 if step_idx == 0 else step_idx * 6
                msg = {
                    **step,
                    "id": f"{st['session']['id']}-m{step_idx + 1}",
                    "offsetSec": offset_sec,
                    "timestamp": (st["baseDt"] + timedelta(seconds=offset_sec)).isoformat().replace("+00:00", "Z"),
                }
                st["session"]["messages"] = [*st["session"]["messages"], msg]
                msgs = st["session"]["messages"]
                st["session"]["agents"] = [
                    {
                        **a,
                        "status": (
                            "speaking"
                            if a["id"] == step["fromAgentId"]
                            else (
                                "waiting"
                                if (a["id"] == step["toAgentId"] or step["toAgentId"] == "all")
                                else ("waiting" if any(m["fromAgentId"] == a["id"] for m in msgs) else "idle")
                            )
                        ),
                    }
                    for a in st["session"]["agents"]
                ]
                snapshot = dict(st["session"])
                done = st["index"] >= len(st["steps"])
            self.store.upsert_simulated_session(snapshot)
            return not done

        tick()
        tick()

        def runner() -> None:
            while not stop_ev.wait(interval_sec):
                if not tick():
                    stop_ev.wait(min(interval_sec, 1.2))
                    self.stop_simulation()
                    break

        threading.Thread(target=runner, daemon=True).start()
        return session["id"]

    def start(self, host: str = "127.0.0.1", port: int = 4242) -> int:
        dash = self
        self.host = host

        class DashboardHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, status: int, data: Any) -> None:
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_json_body(self, limit: int = 512 * 1024) -> dict[str, Any]:
                cl = int(self.headers.get("Content-Length") or 0)
                if cl > limit:
                    raise ValueError("Payload too large")
                raw = self.rfile.read(cl).decode("utf-8") if cl > 0 else ""
                return json.loads(raw) if raw.strip() else {}

            def do_GET(self) -> None:
                parsed = urlparse(self.path or "/")
                pathname = parsed.path
                qs = parse_qs(parsed.query)

                if pathname == "/api/health":
                    with dash._lock:
                        px_up = dash.proxy_instance is not None
                    self._send_json(200, {"ok": True, "version": __version__, "pid": os.getpid(), "proxyUp": px_up})
                    return

                if pathname == "/api/state":
                    mode = (qs.get("mode") or ["auto"])[0]
                    dash.store.reload()
                    self._send_json(200, dash.build_payload(mode))
                    return

                if pathname == "/api/events":
                    mode = (qs.get("mode") or ["auto"])[0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    q: queue.Queue[str | None] = queue.Queue(maxsize=32)
                    entry = (q, mode)
                    with dash._lock:
                        dash._sse_clients.add(entry)
                    try:
                        initial = f"event: state\ndata: {json.dumps(dash.build_payload(mode))}\n\n"
                        self.wfile.write(initial.encode("utf-8"))
                        self.wfile.flush()
                        while True:
                            try:
                                msg = q.get(timeout=20.0)
                                if msg is None:
                                    break
                                self.wfile.write(msg.encode("utf-8"))
                                self.wfile.flush()
                            except queue.Empty:
                                self.wfile.write(b": ping\n\n")
                                self.wfile.flush()
                    except Exception:
                        pass
                    finally:
                        with dash._lock:
                            dash._sse_clients.discard(entry)
                    return

                if pathname == "/api/config":
                    cfg = load_config(dash.data_dir)
                    policy = build_policy_prompt(cfg, cwd=dash.active_graph_dir, data_dir=dash.data_dir, preview=True)
                    self._send_json(200, {"config": cfg, "policy": policy})
                    return

                if pathname == "/api/graph/query":
                    q_term = (qs.get("q") or [""])[0]
                    self._send_json(200, query_knowledge_graph(dash.active_graph, q_term))
                    return

                if pathname == "/api/memories":
                    items = search_memories(
                        query=(qs.get("q") or [""])[0],
                        project=(qs.get("project") or [""])[0],
                        kind=(qs.get("kind") or [""])[0],
                        limit=50,
                        override_dir=dash.data_dir,
                    )
                    self._send_json(200, {"items": items})
                    return

                if pathname == "/api/card.svg":
                    mode = (qs.get("mode") or ["auto"])[0]
                    scope = (qs.get("scope") or ["session"])[0]
                    session_id = (qs.get("sessionId") or [""])[0]
                    theme = "slate" if (qs.get("theme") or [""])[0] == "slate" else "black"
                    payload = dash.build_payload(mode)
                    if scope == "portfolio":
                        p = payload["portfolio"]
                        proj_w = "project" if p["projectCount"] == 1 else "projects"
                        sess_w = "session" if p["sessionCount"] == 1 else "sessions"
                        svg = render_share_card_svg(
                            scope_label=f"{p['projectCount']} {proj_w} · {p['sessionCount']} {sess_w}",
                            duration_sec=p["durationSec"],
                            signal_pct=p["signalPct"],
                            total_messages=p["totalMessages"],
                            total_tokens=p["totalTokens"],
                            total_cost_usd=p["totalCostUsd"],
                            chatter_tax_usd=p["chatterTaxUsd"],
                            top_agents=p["topAgents"],
                            theme=theme,
                        )
                    else:
                        sess = next((s for s in payload["sessions"] if s["id"] == session_id), None)
                        if not sess and payload["sessions"]:
                            sess = payload["sessions"][0]
                        if not sess:
                            svg = render_share_card_svg(scope_label="No sessions recorded", theme=theme)
                        else:
                            sm = sess["summary"]
                            svg = render_share_card_svg(
                                scope_label=f"{sess['project']} · {len(sess['agents'])} agents",
                                duration_sec=sm["durationSec"],
                                signal_pct=sm["signalPct"],
                                total_messages=sm["agentTurns"],
                                total_tokens=sm["totalTokens"],
                                total_cost_usd=sm["totalCostUsd"],
                                chatter_tax_usd=sm["chatterTaxUsd"],
                                top_agents=sess["agents"],
                                theme=theme,
                            )
                    raw_svg = svg.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(raw_svg)))
                    self.end_headers()
                    self.wfile.write(raw_svg)
                    return

                # Static UI assets
                rel = "index.html" if pathname == "/" else pathname.lstrip("/")
                safe = (UI_DIR / rel).resolve()
                try:
                    safe.relative_to(UI_DIR)
                except ValueError:
                    self._send_404()
                    return
                if not safe.exists() or safe.is_dir():
                    self._send_404()
                    return
                content = safe.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", MIME_TYPES.get(safe.suffix.lower(), "application/octet-stream"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _send_404(self) -> None:
                body = b"Not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                pathname = urlparse(self.path or "/").path
                try:
                    body = self._read_json_body()
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                    return

                try:
                    if pathname == "/api/config":
                        cfg = save_config(body, dash.data_dir)
                        policy = build_policy_prompt(cfg, cwd=dash.active_graph_dir, data_dir=dash.data_dir, preview=True)
                        dash.broadcast("state")
                        self._send_json(200, {"ok": True, "config": cfg, "policy": policy})
                        return

                    if pathname == "/api/compress":
                        cfg = load_config(dash.data_dir)
                        mode = body.get("mode") or ("on" if cfg.get("compression") == "off" else cfg.get("compression", "on"))
                        res = compress_tool_output(body.get("text", ""), mode=mode)
                        if body.get("record") is not False and res["savedTokens"] > 0:
                            record_compression_saving(
                                {"source": "dashboard", "label": body.get("label") or "interactive log", "mode": mode, **res},
                                dash.data_dir,
                            )
                            dash.broadcast("state")
                        self._send_json(200, res)
                        return

                    if pathname == "/api/compress-doc":
                        self._send_json(200, compress_markdown_text(body.get("text", "")))
                        return

                    if pathname == "/api/proxy/start":
                        info = dash.start_proxy(body.get("port"), body.get("upstream"), body.get("omniUpstream"))
                        self._send_json(200, {"ok": True, **info})
                        return

                    if pathname == "/api/proxy/stop":
                        dash.stop_proxy()
                        self._send_json(200, {"ok": True})
                        return

                    if pathname == "/api/graph/build":
                        target = Path(body["dir"]).resolve() if body.get("dir") else dash.active_graph_dir
                        graph = build_knowledge_graph(target, persist=body.get("persist") is not False)
                        with dash._lock:
                            dash.active_graph = graph
                            dash.active_graph_dir = target
                            dash.active_repo_audit = None
                        dash.broadcast("state")
                        self._send_json(200, {"ok": True, "graph": graph})
                        return

                    if pathname == "/api/audit":
                        target = Path(body["dir"]).resolve() if body.get("dir") else dash.active_graph_dir
                        audit = run_repo_audit(target)
                        with dash._lock:
                            dash.active_repo_audit = audit
                        dash.broadcast("state")
                        self._send_json(200, {"ok": True, "audit": audit})
                        return

                    if pathname == "/api/memories":
                        entry = add_memory({**body, "source": body.get("source") or "dashboard"}, dash.data_dir)
                        dash.broadcast("state")
                        self._send_json(201, {"ok": True, "entry": entry})
                        return

                    if pathname == "/api/memories/summarize":
                        mode = body.get("mode") or "auto"
                        sessions = dash.store.get_sessions(mode)["sessions"]
                        sess = next((s for s in sessions if s["id"] == body.get("sessionId")), None)
                        if not sess and sessions:
                            sess = sessions[0]
                        if not sess:
                            self._send_json(404, {"error": "No session available to summarize"})
                            return
                        entry = summarize_session_to_memory(sess, dash.data_dir)
                        dash.broadcast("state")
                        self._send_json(201, {"ok": True, "entry": entry})
                        return

                    if pathname == "/api/hooks/event":
                        if not body.get("sessionId"):
                            self._send_json(400, {"error": "Missing sessionId"})
                            return
                        dash.store.record_hook_event(body)
                        self._send_json(202, {"ok": True, "id": body.get("id")})
                        return

                    if pathname == "/api/simulate/start":
                        sid = dash.start_simulation()
                        self._send_json(200, {"ok": True, "sessionId": sid})
                        return

                    if pathname == "/api/simulate/stop":
                        dash.stop_simulation()
                        self._send_json(200, {"ok": True})
                        return

                    self._send_404()
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})

            def do_DELETE(self) -> None:
                pathname = urlparse(self.path or "/").path
                if pathname.startswith("/api/memories/"):
                    mem_id = unquote(pathname[len("/api/memories/") :])
                    removed = delete_memory(mem_id, dash.data_dir)
                    if removed:
                        dash.broadcast("state")
                    self._send_json(200 if removed else 404, {"ok": removed})
                    return
                self._send_404()

        class ReusableThreadingHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._httpd = ReusableThreadingHTTPServer((host, port), DashboardHandler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self.stop_simulation()
        self.stop_proxy()
        with self._lock:
            clients = list(self._sse_clients)
            self._sse_clients.clear()
        for q, _ in clients:
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
