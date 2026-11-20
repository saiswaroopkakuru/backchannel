"""Unified CLI for backchannel v3.0.0 (6-in-1 Claude Code plugin, MCP server, proxy, and dashboard)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from . import __version__
from .analyzer import iso_now, summarize_portfolio
from .card import format_compact_tokens, format_duration, render_share_card_svg
from .compressor import (
    compress_tool_output,
    compute_headroom_summary,
    load_savings_ledger,
    record_compression_saving,
)
from .config import (
    VALID_ENUMS,
    load_config,
    read_omniroute_settings,
    resolve_omniroute_upstream,
    resolve_proxy_upstream,
    save_config,
)
from .daemon import (
    clear_daemon_state,
    get_daemon_status,
    start_background_daemon,
    stop_background_daemon,
    write_daemon_state,
)
from .doc_compress import compress_markdown_file
from .graphify import build_knowledge_graph, load_knowledge_graph, query_knowledge_graph
from .memory import add_memory, delete_memory, load_memories, search_memories, summarize_session_to_memory
from .modes import build_policy_prompt
from .proxy import HeadroomProxyServer
from .repo_audit import run_repo_audit
from .server import DashboardServer
from .store import BackchannelStore


def _parse_args(argv: list[str]) -> tuple[str, list[str], dict[str, Any]]:
    args = list(argv)
    cmd = args.pop(0) if args and not args[0].startswith("-") else "up"
    positionals: list[str] = []
    flags: dict[str, Any] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if cmd in ("wrap", "claude", "claude-omni"):
            positionals.append(token)
            i += 1
            continue
        if token.startswith("--"):
            key = token[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                flags[key] = args[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positionals.append(token)
            i += 1
    return cmd, positionals, flags


def _print_help() -> None:
    print(
        f"""backchannel v{__version__} — Complete 6-in-1 Claude Code Plugin Suite (Python)
(Backchannel · Caveman · Ponytail · Headroom Proxy · OmniRoute · Graphify · Claude-Mem · MCP)

One-command background stack:
  backchannel all [--open]                                    Enable & start EVERYTHING (6 engines + Dashboard + Proxy + OmniRoute + Graph)
  backchannel up [--port 4242] [--proxy-port 4243] [--open]   Start ALL 6 engines in the background
  backchannel claude [--omni] [claude-args...]                Auto-start background suite & run Claude via proxy
  backchannel claude-omni [claude-args...]                    Run Claude via Backchannel -> OmniRoute (:20128)
  backchannel ps                                              Show background daemon status & PID
  backchannel down                                            Stop the background daemon cleanly

Individual engine commands:
  backchannel dashboard [--port 4242] [--demo] [--no-open]    Run dashboard in foreground
  backchannel proxy [--port 4243]                             Run standalone Headroom/OmniRoute proxy in foreground
  backchannel status [--demo] [--json]                        Unified 6-in-1 status summary
  backchannel mode [voice|minimalism|compression|graph|memory] [value]
  backchannel graph build [dir] | query <term> [dir]          Graphify 16-lang + PDF knowledge graph
  backchannel audit [dir] [--json]                            Ponytail repo-wide minimalism audit
  backchannel compress [file] [--mode on|aggressive]          Headroom log compressor
  backchannel compress-doc <file.md> [--dry-run]              Caveman CLAUDE.md/markdown compressor
  backchannel wrap <command...>                               Run command through Headroom log compression
  backchannel mem list | search <q> | add "<text>" | summarize | rm <id>
  backchannel card [--out ./backchannel-card.svg] [--session <id>] [--theme black|slate]
  backchannel doctor                                          Check runtime, hooks, MCP, daemon, and stores"""
    )


def _probe_http_up(url: str, timeout: float = 1.0) -> bool:
    try:
        with urlopen(url, timeout=timeout):
            return True
    except Exception as exc:
        # HTTP errors (e.g. 401/404) still prove the server is listening
        return hasattr(exc, "code")


def _ensure_omniroute_up(omni_url: str) -> bool:
    if _probe_http_up(omni_url, 1.0):
        return True
    if os.name == "nt":
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "Start-ScheduledTask -TaskName OmniRoute -ErrorAction SilentlyContinue"],
                capture_output=True,
                timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
        for _ in range(6):
            time.sleep(0.5)
            if _probe_http_up(omni_url, 0.8):
                return True
    return False


def _run_all(flags: dict[str, Any]) -> None:
    cfg = load_config()
    patch: dict[str, Any] = {}
    if cfg.get("voice") == "off":
        patch["voice"] = "terse"
    if cfg.get("minimalism") == "off":
        patch["minimalism"] = "full"
    if cfg.get("compression") == "off":
        patch["compression"] = "on"
    if not cfg.get("graphAssist"):
        patch["graphAssist"] = True
    if not cfg.get("memoryAssist"):
        patch["memoryAssist"] = True
    if patch:
        cfg = save_config(patch)

    graph_dir = str(Path(flags["graph-dir"]).resolve()) if isinstance(flags.get("graph-dir"), str) else os.getcwd()
    info = start_background_daemon(
        port=int(flags["port"]) if flags.get("port") else cfg["dashboardPort"],
        proxy_port=int(flags["proxy-port"]) if flags.get("proxy-port") else cfg["proxyPort"],
        upstream=flags["upstream"] if isinstance(flags.get("upstream"), str) else None,
        omni_upstream=flags["omni-upstream"] if isinstance(flags.get("omni-upstream"), str) else None,
        graph_dir=graph_dir,
        demo=bool(flags.get("demo")),
    )

    omni_up = _ensure_omniroute_up(info["omniUpstream"])
    try:
        graph = build_knowledge_graph(graph_dir, persist=True)
    except Exception:
        graph = None

    print(f"backchannel v{__version__} — ALL ENGINES ACTIVE (pid {info['pid']})")
    print(f"  Dashboard      : {info['dashboardUrl']}")
    print(f"  Primary proxy  : {info['proxyUrl']} -> {info['upstream']}")
    print(f"  OmniRoute proxy: {info['omniProxyUrl']} -> {info['omniUpstream']} ({'UP' if omni_up else 'not running'})")
    if graph:
        st = graph["stats"]
        print(f"  Graphify index : {st['fileCount']} files · {st['symbolCount']} symbols · {st['edgeCount']} edges ({graph['project']})")
    print(f"  Engines        : Caveman({cfg['voice']}) · Ponytail({cfg['minimalism']}) · Headroom({cfg['compression']}) · Graphify(on) · Claude-Mem(on) · MCP(13 tools)")

    if flags.get("open") and os.environ.get("CI") != "true":
        webbrowser.open(info["dashboardUrl"])


def _run_up(flags: dict[str, Any]) -> None:
    cfg = load_config()
    info = start_background_daemon(
        port=int(flags["port"]) if flags.get("port") else cfg["dashboardPort"],
        proxy_port=int(flags["proxy-port"]) if flags.get("proxy-port") else cfg["proxyPort"],
        upstream=flags["upstream"] if isinstance(flags.get("upstream"), str) else None,
        omni_upstream=flags["omni-upstream"] if isinstance(flags.get("omni-upstream"), str) else None,
        graph_dir=flags["graph-dir"] if isinstance(flags.get("graph-dir"), str) else os.getcwd(),
        demo=bool(flags.get("demo")),
    )
    msg = (
        f"backchannel v{__version__} is already running in the background (pid {info['pid']})"
        if info.get("alreadyRunning")
        else f"backchannel v{__version__} started in the background (pid {info['pid']})"
    )
    print(msg)
    print(f"  Dashboard      : {info['dashboardUrl']}  (Backchannel · Audit · Graphify · Claude-Mem · Card)")
    print(f"  Headroom proxy : {info['proxyUrl']} -> {info['upstream']}")
    print(f"  OmniRoute proxy: {info['omniProxyUrl']} -> {info['omniUpstream']}")
    print(
        f"  Engines active : Caveman({cfg['voice']}) · Ponytail({cfg['minimalism']}) · Headroom({cfg['compression']}) "
        f"· Graphify({'on' if cfg['graphAssist'] else 'off'}) · Claude-Mem({'on' if cfg['memoryAssist'] else 'off'}) · MCP(13 tools)"
    )
    print(f"  Logs           : {info['logFile']}")
    print("  Launch Claude  : backchannel claude  |  backchannel claude-omni")
    print("  Stop daemon    : backchannel down")
    if flags.get("open") and os.environ.get("CI") != "true":
        webbrowser.open(info["dashboardUrl"])


def _run_down() -> None:
    res = stop_background_daemon()
    if res["stopped"]:
        print(f"Stopped backchannel background daemon (pid {res['pid']}).")
    else:
        print("No running backchannel background daemon found.")


def _run_ps(flags: dict[str, Any]) -> None:
    st = get_daemon_status()
    if flags.get("json"):
        print(json.dumps(st, indent=2))
        return
    status_label = "RUNNING" if st["running"] else "STOPPED"
    pid_suffix = f" (pid {st['pid']})" if st.get("pid") else ""
    print(f"backchannel daemon: {status_label}{pid_suffix}")
    print(f"  Dashboard      : {st['dashboardUrl']} ({'up' if st['dashboardUp'] else 'down'})")
    print(
        f"  Headroom proxy : {st['proxyUrl']} -> {st['upstream']} "
        f"({'up' if st['proxyUp'] else 'down'} · {st['requestsProxied']} reqs · {st['requestsCompressed']} compressed · {st['totalSavedTokens']} tok saved)"
    )
    print(f"  OmniRoute proxy: {st['omniProxyUrl']} -> {st['omniUpstream']} ({st['omniRequestsProxied']} reqs · {st['omniRequestsCompressed']} compressed)")
    if st.get("graphDir"):
        print(f"  Indexed dir    : {st['graphDir']}")
    if st.get("startedAt"):
        print(f"  Started        : {st['startedAt']}")
    print(f"  Log file       : {st['logFile']}")


def _run_daemon_worker(flags: dict[str, Any]) -> None:
    cfg = load_config()
    port = int(flags.get("port") or cfg.get("dashboardPort") or 4242)
    proxy_port = int(flags.get("proxy-port") or cfg.get("proxyPort") or 4243)
    upstream = resolve_proxy_upstream(
        cfg,
        proxy_port=proxy_port,
        upstream=flags["upstream"] if isinstance(flags.get("upstream"), str) else None,
    )
    omni_upstream = resolve_omniroute_upstream(
        cfg,
        proxy_port=proxy_port,
        omni_upstream=flags["omni-upstream"] if isinstance(flags.get("omni-upstream"), str) else None,
    )
    graph_dir = str(Path(flags["graph-dir"]).resolve()) if isinstance(flags.get("graph-dir"), str) else os.getcwd()

    dash = DashboardServer(demo=bool(flags.get("demo")), graph_dir=graph_dir)
    dash.start(host="127.0.0.1", port=port)
    dash.start_proxy(proxy_port, upstream, omni_upstream)

    write_daemon_state(
        {
            "pid": os.getpid(),
            "dashboardPort": port,
            "proxyPort": proxy_port,
            "upstream": upstream,
            "omniUpstream": omni_upstream,
            "graphDir": graph_dir,
            "startedAt": iso_now(),
        }
    )

    def _build_graph_bg() -> None:
        try:
            build_knowledge_graph(graph_dir, persist=True)
        except Exception:
            pass

    threading.Thread(target=_build_graph_bg, daemon=True).start()
    print(
        f"[{iso_now()}] backchannel daemon online: dashboard=:{port} proxy=:{proxy_port} "
        f"upstream={upstream} omniUpstream={omni_upstream} graphDir={graph_dir}",
        flush=True,
    )

    stop_event = threading.Event()

    def _handle_sig(*_: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    finally:
        dash.stop()
        clear_daemon_state()


def _resolve_claude_executable() -> str:
    if os.name == "nt":
        local_exe = Path.home() / ".local" / "bin" / "claude.exe"
        if local_exe.exists():
            return str(local_exe)
    found = shutil.which("claude")
    return found or "claude"


def _run_claude_wrapped(positionals: list[str], *, force_omni: bool = False) -> None:
    use_omni = force_omni
    forwarded: list[str] = []
    for arg in positionals:
        if not use_omni and arg in ("--omni", "--omniroute"):
            use_omni = True
            continue
        forwarded.append(arg)

    info = start_background_daemon(graph_dir=os.getcwd())
    target_proxy = info["omniProxyUrl"] if use_omni else info["proxyUrl"]
    target_up = info["omniUpstream"] if use_omni else info["upstream"]
    label = "OmniRoute " if use_omni else ""
    print(
        f"[backchannel] All 6 engines active in background (dashboard {info['dashboardUrl']} · {label}proxy {target_proxy} -> {target_up})",
        file=sys.stderr,
    )

    has_settings = any(a == "--settings" or a.startswith("--settings=") for a in forwarded)
    base_env: dict[str, str] = {"ANTHROPIC_BASE_URL": target_proxy}
    if use_omni:
        omni_cfg = read_omniroute_settings()
        if isinstance(omni_cfg, dict) and isinstance(omni_cfg.get("env"), dict):
            base_env.update({str(k): str(v) for k, v in omni_cfg["env"].items()})
            base_env["ANTHROPIC_BASE_URL"] = target_proxy
            base_env["ENABLE_TOOL_SEARCH"] = "true"

    claude_args = forwarded if has_settings else ["--settings", json.dumps({"env": base_env}), *forwarded]
    exe = _resolve_claude_executable()
    proc = subprocess.run([exe, *claude_args], env={**os.environ, **base_env})
    sys.exit(proc.returncode)


def _run_status(flags: dict[str, Any]) -> None:
    store = BackchannelStore(demo=bool(flags.get("demo")))
    res = store.get_sessions("demo" if flags.get("demo") else "auto")
    portfolio = summarize_portfolio(res["sessions"])
    cfg = load_config()
    ledger = load_savings_ledger()
    headroom = compute_headroom_summary(res["sessions"], ledger, cfg)
    memories = load_memories()

    if flags.get("json"):
        print(
            json.dumps(
                {
                    "activeSource": res["activeSource"],
                    "counts": res["counts"],
                    "config": cfg,
                    "headroom": headroom,
                    "memoryCount": len(memories),
                    "portfolio": portfolio,
                    "sessions": res["sessions"],
                },
                indent=2,
            )
        )
        return

    print(f"backchannel v{__version__} ({res['activeSource']} · {portfolio['sessionCount']} sessions · {portfolio['projectCount']} projects)")
    print(
        f"  Engines      : voice={cfg['voice']} · minimalism={cfg['minimalism']} · compression={cfg['compression']} "
        f"· graph={'on' if cfg['graphAssist'] else 'off'} · mem={'on' if cfg['memoryAssist'] else 'off'}"
    )
    print(f"  Signal ratio : {portfolio['signalPct']:.1f}% ({portfolio['fillerPct']:.1f}% filler)")
    print(f"  Messages     : {portfolio['totalMessages']} agent turns")
    print(f"  Tokens       : {format_compact_tokens(portfolio['totalTokens'])} total (cache hit {headroom['cache']['cacheHitPct']}%)")
    print(
        f"  Cost         : ${portfolio['totalCostUsd']:.2f} (chatter tax: ${portfolio['chatterTaxUsd']:.2f} "
        f"· 5h window: ${headroom['window5h']['spendUsd']:.2f}/${headroom['window5h']['budgetUsd']})"
    )
    print(f"  Talk time    : {format_duration(portfolio['durationSec'])}")
    print(f"  Memories     : {len(memories)} saved observations")
    if res["sessions"]:
        latest = res["sessions"][0]
        print(f"\nLatest session: {latest['title']} [{latest['project']}]")
        print(f"  {latest['finding']}")


def _run_mode(positionals: list[str]) -> None:
    key = positionals[0] if len(positionals) > 0 else None
    val = positionals[1] if len(positionals) > 1 else None
    if not key:
        cfg = load_config()
        policy = build_policy_prompt(cfg, cwd=os.getcwd(), preview=True)
        print("Active backchannel modes (~/.backchannel/config.json):")
        print(f"  voice (Caveman)        : {cfg['voice']}  (off | terse | ultra | megacave)")
        print(f"  minimalism (Ponytail)  : {cfg['minimalism']}  (off | lite | full | ultra)")
        print(f"  compression (Headroom) : {cfg['compression']}  (off | on | aggressive)")
        print(f"  graph (Graphify)       : {'on' if cfg['graphAssist'] else 'off'}")
        print(f"  memory (Claude-Mem)    : {'on' if cfg['memoryAssist'] else 'off'}")
        print(f"\nSessionStart prompt footprint: ~{policy['estimatedTokens']} tokens")
        if policy["text"]:
            print(f"\n{policy['text']}")
        return

    patch: dict[str, Any] = {}
    if key in ("voice", "caveman"):
        if val not in VALID_ENUMS["voice"]:
            print(f'Invalid voice "{val}". Use: {", ".join(VALID_ENUMS["voice"])}', file=sys.stderr)
            sys.exit(1)
        patch["voice"] = val
    elif key in ("minimalism", "ponytail", "lean"):
        if val not in VALID_ENUMS["minimalism"]:
            print(f'Invalid minimalism "{val}". Use: {", ".join(VALID_ENUMS["minimalism"])}', file=sys.stderr)
            sys.exit(1)
        patch["minimalism"] = val
    elif key in ("compression", "headroom"):
        if val not in VALID_ENUMS["compression"]:
            print(f'Invalid compression "{val}". Use: {", ".join(VALID_ENUMS["compression"])}', file=sys.stderr)
            sys.exit(1)
        patch["compression"] = val
    elif key in ("graph", "graphify"):
        patch["graphAssist"] = val not in ("off", "false", "0")
    elif key in ("memory", "mem"):
        patch["memoryAssist"] = val not in ("off", "false", "0")
    else:
        print(f"Unknown mode key: {key}. Use: voice | minimalism | compression | graph | memory", file=sys.stderr)
        sys.exit(1)

    nxt = save_config(patch)
    print(f"Updated {key} -> {json.dumps(nxt)}")


def _run_graph(positionals: list[str], flags: dict[str, Any]) -> None:
    sub = positionals[0] if positionals else "build"
    if sub == "query":
        q = positionals[1] if len(positionals) > 1 else ""
        target = positionals[2] if len(positionals) > 2 else os.getcwd()
        graph = load_knowledge_graph(target) or build_knowledge_graph(target, persist=True)
        res = query_knowledge_graph(graph, q)
        if flags.get("json"):
            print(json.dumps(res, indent=2))
            return
        print(f'Graphify query "{q}" in {graph["project"]} ({len(res["matches"])} matches · {graph["stats"]["compressionRatio"]}x graph savings):')
        for m in res["matches"][:10]:
            syms = ", ".join((m.get("matchedSymbols") or m.get("symbols") or [])[:5])
            print(f"  {m['id']}  [cluster={m.get('cluster') or m['community']}, rank={m['rank']}, in={m['inDegree']}, out={m['outDegree']}]  {syms}")
        return

    target = positionals[1] if sub == "build" and len(positionals) > 1 else (sub if sub != "build" else os.getcwd())
    graph = build_knowledge_graph(target, persist=True)
    if flags.get("json"):
        print(json.dumps(graph, indent=2))
        return
    st = graph["stats"]
    print(f"Graphify index built for {graph['project']} -> {Path(graph['rootDir']) / '.backchannel' / 'graph.json'}")
    print(
        f"  Files: {st['fileCount']} ({st['pdfCount']} PDFs) · Symbols: {st['symbolCount']} "
        f"· Edges: {st['edgeCount']} · Communities: {st['communityCount']}"
    )
    print(
        f"  Token compression: ~{format_compact_tokens(st['rawRepoTokens'])} raw -> "
        f"~{format_compact_tokens(st['graphTokens'])} graph ({st['compressionRatio']}x)"
    )


def _run_audit(positionals: list[str], flags: dict[str, Any]) -> None:
    target = positionals[0] if positionals else os.getcwd()
    audit = run_repo_audit(target)
    if flags.get("json"):
        print(json.dumps(audit, indent=2))
        return
    print(f"Ponytail minimalism audit for {audit['project']} — score {audit['score']}/100 ({audit['filesScanned']} files scanned)")
    c = audit["counts"]
    print(f"  Findings: {c['total']} total ({c['high']} high · {c['medium']} medium · {c['low']} low)")
    for f in audit["findings"][:15]:
        print(f"  [{f['severity'].upper()}] {f['title']} ({f['location']})\n    {f['detail']}")


def _run_compress(positionals: list[str], flags: dict[str, Any]) -> None:
    mode = str(flags.get("mode") or load_config().get("compression") or "on")
    if positionals:
        raw = Path(positionals[0]).read_text(encoding="utf-8", errors="replace")
        label = Path(positionals[0]).name
    else:
        raw = sys.stdin.read()
        label = "stdin"
    res = compress_tool_output(raw, mode=mode)
    if res["savedTokens"] > 0:
        record_compression_saving({"source": "cli:compress", "label": label, "mode": mode, **res})
    sys.stdout.write(res["text"] + "\n")
    print(
        f"[headroom] {res['origTokens']} -> {res['compressedTokens']} tok (-{res['savedPct']}%, rules: {', '.join(res['rulesApplied']) or 'none'})",
        file=sys.stderr,
    )


def _run_compress_doc(positionals: list[str], flags: dict[str, Any]) -> None:
    if not positionals:
        print("Usage: backchannel compress-doc <CLAUDE.md> [--dry-run]", file=sys.stderr)
        sys.exit(1)
    dry_run = bool(flags.get("dry-run"))
    res = compress_markdown_file(positionals[0], write=not dry_run)
    if dry_run:
        sys.stdout.write(res["text"])
    print(
        f"[caveman doc] {res['origTokens']} -> {res['compressedTokens']} tok (-{res['savedPct']}%)"
        + (f" · backup: {res['backupPath']}" if res.get("backupPath") else " (dry-run)"),
        file=sys.stderr,
    )


def _run_wrap(positionals: list[str]) -> None:
    if not positionals:
        print("Usage: backchannel wrap <command...>", file=sys.stderr)
        sys.exit(1)
    proc = subprocess.run(positionals, capture_output=True, text=True, shell=(os.name == "nt"))
    combined = (proc.stdout or "") + (f"\n{proc.stderr}" if proc.stderr else "")
    mode = load_config().get("compression") or "on"
    res = compress_tool_output(combined, mode=mode)
    if res["savedTokens"] > 0:
        record_compression_saving({"source": "cli:wrap", "label": " ".join(positionals)[:60], "mode": mode, **res})
    sys.stdout.write(res["text"] + "\n")
    print(f"[headroom wrap] {res['origTokens']} -> {res['compressedTokens']} tok (-{res['savedPct']}%, exit {proc.returncode})", file=sys.stderr)
    sys.exit(proc.returncode)


def _run_proxy(flags: dict[str, Any]) -> None:
    cfg = load_config()
    port = int(flags.get("port") or cfg.get("proxyPort") or 4243)
    upstream = resolve_proxy_upstream(cfg, proxy_port=port, upstream=flags["upstream"] if isinstance(flags.get("upstream"), str) else None)
    omni_up = resolve_omniroute_upstream(cfg, proxy_port=port, omni_upstream=flags["omni-upstream"] if isinstance(flags.get("omni-upstream"), str) else None)
    px = HeadroomProxyServer(port=port, upstream=upstream, omni_upstream=omni_up)
    bound = px.start()
    print(f"Headroom in-flight compression proxy listening at http://127.0.0.1:{bound}")
    print(f"  Upstream  : {upstream}")
    print(f"  OmniRoute : http://127.0.0.1:{bound}/omni -> {omni_up}")
    print("  Use with  : backchannel claude  |  backchannel claude-omni")
    print("  Stop      : Ctrl+C")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        px.stop()


def _run_mem(positionals: list[str], flags: dict[str, Any]) -> None:
    sub = positionals[0] if positionals else "list"
    if sub == "add":
        text = " ".join(positionals[1:]).strip()
        if not text:
            print('Usage: backchannel mem add "<observation>" [--kind bugfix] [--project name] [--tags a,b]', file=sys.stderr)
            sys.exit(1)
        entry = add_memory(
            {
                "title": flags.get("title") or text[:90],
                "body": text,
                "kind": flags.get("kind") or "pattern",
                "project": flags.get("project") or Path(os.getcwd()).name,
                "tags": flags.get("tags") or "",
                "source": "cli",
            }
        )
        print(f"Saved memory {entry['id']} [{entry['kind']}] ({entry['project']}): {entry['title']}")
        return
    if sub == "summarize":
        store = BackchannelStore()
        sessions = store.get_sessions("auto")["sessions"]
        if not sessions:
            print("No sessions available to summarize.")
            return
        entry = summarize_session_to_memory(sessions[0])
        if entry:
            print(f"Summarized latest session -> {entry['id']} [{entry['project']}]: {entry['title']}")
        return
    if sub in ("rm", "delete"):
        ok = delete_memory(positionals[1] if len(positionals) > 1 else "")
        print(f"Deleted {positionals[1]}" if ok else f"Memory not found: {positionals[1] if len(positionals) > 1 else ''}")
        return
    if sub == "search":
        q = " ".join(positionals[1:]).strip()
        items = search_memories(query=q, project=str(flags.get("project") or ""), kind=str(flags.get("kind") or ""), limit=20)
        if flags.get("json"):
            print(json.dumps(items, indent=2))
            return
        print(f'Claude-Mem hybrid search "{q}" ({len(items)} matches):')
        for m in items:
            print(f"  {m['id']} [{m['kind']} · {m['project']} · score={m.get('score', 0)}] {m['title']}")
        return

    items = load_memories()
    if flags.get("json"):
        print(json.dumps(items, indent=2))
        return
    print(f"Claude-Mem observations ({len(items)} stored):")
    for m in items[:25]:
        print(f"  {m['id']} [{m['kind']} · {m['project']}] {m['title']}")


def _run_card(flags: dict[str, Any]) -> None:
    store = BackchannelStore(demo=bool(flags.get("demo")))
    sessions = store.get_sessions("demo" if flags.get("demo") else "auto")["sessions"]
    theme = "slate" if flags.get("theme") == "slate" else "black"
    if isinstance(flags.get("session"), str):
        sess = next((s for s in sessions if s["id"] == flags["session"]), sessions[0] if sessions else None)
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
    else:
        p = summarize_portfolio(sessions)
        svg = render_share_card_svg(
            scope_label=f"{p['projectCount']} {'project' if p['projectCount'] == 1 else 'projects'} · {p['sessionCount']} {'session' if p['sessionCount'] == 1 else 'sessions'}",
            duration_sec=p["durationSec"],
            signal_pct=p["signalPct"],
            total_messages=p["totalMessages"],
            total_tokens=p["totalTokens"],
            total_cost_usd=p["totalCostUsd"],
            chatter_tax_usd=p["chatterTaxUsd"],
            top_agents=p["topAgents"],
            theme=theme,
        )
    out_path = Path(flags["out"]).resolve() if isinstance(flags.get("out"), str) else Path("backchannel-card.svg").resolve()
    out_path.write_text(svg, encoding="utf-8")
    print(f"Wrote backchannel share card to {out_path}")


def _run_doctor() -> None:
    store = BackchannelStore()
    diag = store.get_diagnostics()
    cfg = load_config()
    mems = load_memories()
    ledger = load_savings_ledger()
    daemon = get_daemon_status()
    print(f"backchannel v{__version__} doctor (Python)")
    print(f"  Python runtime   : {sys.version.split()[0]}")
    if daemon["running"]:
        print(
            f"  Background stack : RUNNING (pid {daemon['pid']} · dashboard {daemon['dashboardUrl']} "
            f"· proxy {daemon['proxyUrl']} -> {daemon['upstream']} · omni {daemon['omniProxyUrl']} -> {daemon['omniUpstream']})"
        )
    else:
        print("  Background stack : stopped (run: backchannel all)")
    print(
        f"  Active engines   : voice={cfg['voice']} · minimalism={cfg['minimalism']} · compression={cfg['compression']} "
        f"· graph={'on' if cfg['graphAssist'] else 'off'} · memory={'on' if cfg['memoryAssist'] else 'off'}"
    )
    print("  MCP server       : python -m backchannel.mcp (13 native Claude Code tools)")
    hook_info = f"{diag['hookEventCount']} events" if diag["eventsExists"] else "not created yet"
    proj_info = f"{diag['transcriptSessionCount']} sessions detected" if diag["claudeExists"] else "directory not found"
    print(f"  Hook store       : {diag['eventsFile']} ({hook_info})")
    print(f"  Claude projects  : {diag['claudeProjectsDir']} ({proj_info})")
    print(f"  Headroom ledger  : {len(ledger)} compression runs recorded")
    print(f"  Claude-Mem store : {len(mems)} persistent observations")


def _run_dashboard(flags: dict[str, Any]) -> None:
    cfg = load_config()
    port = int(flags.get("port") or os.environ.get("BACKCHANNEL_PORT") or cfg.get("dashboardPort") or 4242)
    proxy_port = int(flags.get("proxy-port") or cfg.get("proxyPort") or 4243)
    host = flags["host"] if isinstance(flags.get("host"), str) else "127.0.0.1"
    dash = DashboardServer(
        demo=bool(flags.get("demo")),
        graph_dir=flags["graph-dir"] if isinstance(flags.get("graph-dir"), str) else None,
    )
    dash.start(host=host, port=port)
    upstream = resolve_proxy_upstream(cfg, proxy_port=proxy_port)
    omni_up = resolve_omniroute_upstream(cfg, proxy_port=proxy_port)
    if not flags.get("no-proxy"):
        try:
            dash.start_proxy(proxy_port, upstream, omni_up)
        except Exception:
            pass
    url = f"http://{host}:{port}"
    print(f"backchannel v{__version__} dashboard running at {url}")
    print(f"  Headroom proxy : http://127.0.0.1:{proxy_port} -> {upstream}")
    print(f"  OmniRoute proxy: http://127.0.0.1:{proxy_port}/omni -> {omni_up}")
    print(f"  Mode           : {'demo' if flags.get('demo') else 'auto (live transcripts + hooks, demo fallback)'}")
    print(
        f"  Engines        : Caveman({cfg['voice']}) · Ponytail({cfg['minimalism']}) · Headroom({cfg['compression']}) "
        f"· Graphify({'on' if cfg['graphAssist'] else 'off'}) · Claude-Mem({'on' if cfg['memoryAssist'] else 'off'}) · MCP(13 tools)"
    )
    print("  Stop           : Ctrl+C")
    if not flags.get("no-open") and os.environ.get("CI") != "true":
        webbrowser.open(url)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        dash.stop()


def main(argv: list[str] | None = None) -> None:
    cmd, positionals, flags = _parse_args(sys.argv[1:] if argv is None else argv)
    if cmd in ("all", "go"):
        _run_all(flags)
    elif cmd in ("up", "start-all", "daemon"):
        _run_up(flags)
    elif cmd in ("down", "stop"):
        _run_down()
    elif cmd == "ps":
        _run_ps(flags)
    elif cmd == "_daemon-worker":
        _run_daemon_worker(flags)
    elif cmd == "claude":
        _run_claude_wrapped(positionals)
    elif cmd == "claude-omni":
        _run_claude_wrapped(positionals, force_omni=True)
    elif cmd in ("dashboard", "serve", "start"):
        _run_dashboard(flags)
    elif cmd == "status":
        _run_status(flags)
    elif cmd == "mode":
        _run_mode(positionals)
    elif cmd in ("graph", "graphify"):
        _run_graph(positionals, flags)
    elif cmd == "audit":
        _run_audit(positionals, flags)
    elif cmd == "compress":
        _run_compress(positionals, flags)
    elif cmd == "compress-doc":
        _run_compress_doc(positionals, flags)
    elif cmd == "wrap":
        _run_wrap(positionals)
    elif cmd == "proxy":
        _run_proxy(flags)
    elif cmd in ("mem", "memory"):
        _run_mem(positionals, flags)
    elif cmd == "card":
        _run_card(flags)
    elif cmd == "doctor":
        _run_doctor()
    else:
        _print_help()


if __name__ == "__main__":
    main()
