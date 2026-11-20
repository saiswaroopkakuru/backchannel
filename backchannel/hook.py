"""Unified backchannel v3.0.0 Claude Code lifecycle hook collector & policy injector."""

from __future__ import annotations

import json
import os
import random
import re
import string
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .analyzer import analyze_session, iso_now
from .compressor import compress_tool_output, record_compression_saving
from .config import get_data_dir, load_config
from .graphify import load_knowledge_graph, query_knowledge_graph
from .memory import maybe_extract_observation, summarize_session_to_memory
from .modes import build_policy_prompt
from .store import build_sessions_from_hook_events


def _safe_string(value: Any, limit: int = 1600) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value)
    return f"{text[:limit]}..." if len(text) > limit else text


def _project_from_cwd(cwd: Any) -> str:
    if not cwd or not isinstance(cwd, str):
        return "workspace"
    cleaned = cwd.rstrip("\\/")
    return Path(cleaned).name or "workspace"


def normalize_hook_payload(event_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    cwd = payload.get("cwd") or os.getcwd()
    session_id = str(
        payload.get("session_id")
        or payload.get("sessionId")
        or f"hook-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    )
    tool_name = payload.get("tool_name") or payload.get("toolName")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_response = payload.get("tool_response") or payload.get("toolResponse")

    agent_id = payload.get("agent_id") or payload.get("agentId") or tool_input.get("agent_id") or tool_input.get("recipient")
    agent_type = payload.get("agent_type") or payload.get("agentType") or tool_input.get("subagent_type") or tool_input.get("role")

    from_agent = "lead"
    to_agent = "lead"
    kind = "event"
    text = ""

    if event_name == "UserPromptSubmit":
        from_agent, to_agent, kind = "user", "lead", "delegation"
        text = _safe_string(payload.get("prompt") or payload.get("user_prompt") or "")
    elif event_name == "SubagentStart":
        from_agent = "lead"
        to_agent = str(agent_id or agent_type or "subagent")
        kind = "delegation"
        text = _safe_string(payload.get("prompt") or payload.get("description") or f"Spawned {agent_type or 'subagent'} ({to_agent})")
    elif event_name == "SubagentStop":
        from_agent = str(agent_id or agent_type or "subagent")
        to_agent, kind = "lead", "reply"
        text = _safe_string(payload.get("last_assistant_message") or payload.get("output") or f"Subagent {from_agent} completed")
    elif event_name == "PreToolUse":
        from_agent = str(payload.get("agent_id") or "lead")
        to_agent = str(tool_input.get("recipient") or tool_input.get("to") or tool_input.get("subagent_type") or tool_input.get("name") or tool_name or "subagent")
        kind = "peer" if tool_name == "SendMessage" else ("delegation" if tool_name in ("Agent", "Task") else "tool")
        text = _safe_string(tool_input.get("message") or tool_input.get("prompt") or tool_input.get("description") or tool_input.get("subject") or json.dumps(tool_input))
    elif event_name == "PostToolUse":
        from_agent = str(tool_input.get("recipient") or tool_input.get("subagent_type") or tool_name or "tool")
        to_agent = str(payload.get("agent_id") or "lead")
        kind = "reply" if tool_name == "SendMessage" else "tool"
        resp_txt = None
        if isinstance(tool_response, dict):
            resp_txt = tool_response.get("output") or tool_response.get("content") or tool_response.get("summary") or tool_response.get("stdout")
        text = _safe_string(resp_txt or tool_response or f"{tool_name or 'Tool'} completed")
    elif event_name == "TaskCreated":
        from_agent = str(payload.get("agent_id") or "lead")
        to_agent = str(payload.get("assignee") or "all")
        kind = "broadcast"
        text = _safe_string(payload.get("subject") or payload.get("task_subject") or payload.get("description") or "Task created")
    elif event_name == "TaskCompleted":
        from_agent = str(payload.get("agent_id") or payload.get("teammate_name") or "subagent")
        to_agent, kind = "lead", "gate"
        text = _safe_string(payload.get("subject") or payload.get("task_subject") or payload.get("summary") or "Task marked complete")
    elif event_name == "TeammateIdle":
        from_agent = str(payload.get("teammate_name") or payload.get("agent_id") or "teammate")
        to_agent, kind = "lead", "gate"
        text = _safe_string(payload.get("reason") or f"{from_agent} entered idle state")
    elif event_name == "Stop":
        from_agent = str(payload.get("agent_id") or "lead")
        to_agent, kind = "user", "reply"
        text = _safe_string(payload.get("last_assistant_message") or "Turn completed")
    else:
        from_agent = str(payload.get("agent_id") or "lead")
        to_agent, kind = "lead", "event"
        text = _safe_string(payload.get("message") or payload.get("reason") or event_name)

    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return {
        "id": f"ev-{int(time.time() * 1000)}-{rand}",
        "timestamp": payload.get("timestamp") or iso_now(),
        "eventName": event_name,
        "sessionId": session_id,
        "project": _project_from_cwd(cwd),
        "cwd": str(cwd),
        "model": payload.get("model"),
        "agentId": str(agent_id) if agent_id is not None else None,
        "agentType": str(agent_type) if agent_type is not None else None,
        "toolName": tool_name,
        "fromAgent": str(from_agent),
        "toAgent": str(to_agent),
        "kind": kind,
        "text": text,
        "transcriptPath": payload.get("transcript_path") or payload.get("transcriptPath"),
    }


def build_graphify_search_hint(payload: dict[str, Any], config: dict[str, Any]) -> str | None:
    if not config.get("graphAssist"):
        return None
    cwd = payload.get("cwd") or os.getcwd()
    graph = load_knowledge_graph(cwd)
    if not graph:
        return None
    inp = payload.get("tool_input") or payload.get("toolInput") or {}
    raw_query = re.sub(r"[^a-zA-Z0-9_./ -]+", " ", str(inp.get("pattern") or inp.get("query") or "")).strip()
    if len(raw_query) < 3:
        return None
    res = query_knowledge_graph(graph, raw_query)
    if not res.get("matches"):
        return None
    top = "; ".join(f"{m['id']} ({', '.join((m.get('symbols') or [])[:3])})" for m in res["matches"][:4])
    return f'[Graphify hit for "{raw_query}"] {top}. Use MCP tool backchannel_graph_query for 1-hop neighbors.'


def run_hook(event_arg: str = "Unknown", raw_stdin: str | None = None) -> int:
    try:
        if raw_stdin is None:
            raw_stdin = "" if sys.stdin.isatty() else sys.stdin.read()
        raw = raw_stdin.strip()
        payload: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                payload = parsed if isinstance(parsed, dict) else {"message": raw}
            except Exception:
                payload = {"message": raw}

        data_dir = get_data_dir()
        events_file = data_dir / "events.jsonl"
        config = load_config(data_dir)
        port = int(os.environ.get("BACKCHANNEL_PORT") or config.get("dashboardPort") or 4242)
        record = normalize_hook_payload(event_arg, payload)

        if event_arg == "SessionStart":
            policy = build_policy_prompt(config, cwd=record["cwd"], project=record["project"], data_dir=data_dir)
            if policy["text"]:
                sys.stdout.write(policy["text"] + "\n")
                sys.stdout.flush()

        if event_arg == "PreToolUse" and record.get("toolName") in ("Grep", "Glob"):
            hint = build_graphify_search_hint(payload, config)
            if hint:
                sys.stdout.write(
                    json.dumps(
                        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": hint}}
                    )
                    + "\n"
                )
                sys.stdout.flush()
            return 0

        if event_arg == "PostToolUse" and config.get("compression") != "off" and record.get("toolName") == "Bash":
            resp = payload.get("tool_response") or payload.get("toolResponse")
            raw_out = resp if isinstance(resp, str) else ((resp or {}).get("stdout") or (resp or {}).get("output") or "" if isinstance(resp, dict) else "")
            if isinstance(raw_out, str) and len(raw_out) >= 600:
                cmp = compress_tool_output(raw_out, mode=config.get("compression") or "on")
                if cmp["savedTokens"] > 0:
                    cmd_label = _safe_string((payload.get("tool_input") or {}).get("command") or "bash output", 60)
                    record_compression_saving(
                        {"source": "hook:Bash", "label": cmd_label, "mode": config.get("compression") or "on", **cmp},
                        data_dir,
                    )

        if config.get("memoryAssist") and event_arg in ("SubagentStop", "TaskCompleted", "Stop") and record.get("text"):
            maybe_extract_observation(
                text=record["text"],
                project=record["project"],
                source=f"hook:{event_arg}",
                override_dir=data_dir,
            )

        if config.get("memoryAssist") and event_arg == "SessionEnd" and events_file.exists():
            try:
                lines = [ln for ln in events_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                sess_events = []
                for ln in lines[-200:]:
                    try:
                        ev = json.loads(ln)
                        if ev.get("sessionId") == record["sessionId"]:
                            sess_events.append(ev)
                    except Exception:
                        pass
                built = build_sessions_from_hook_events(sess_events)
                if built and len(built[0]["messages"]) >= 2:
                    summarize_session_to_memory(analyze_session(built[0]), data_dir)
            except Exception:
                pass

        if not (event_arg == "PostToolUse" and record.get("toolName") == "Bash"):
            data_dir.mkdir(parents=True, exist_ok=True)
            with events_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            try:
                req = Request(
                    f"http://127.0.0.1:{port}/api/hooks/event",
                    data=json.dumps(record).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=0.25):
                    pass
            except Exception:
                pass
    except Exception:
        pass
    return 0


def main() -> None:
    event_arg = sys.argv[1] if len(sys.argv) > 1 else "Unknown"
    sys.exit(run_hook(event_arg))


if __name__ == "__main__":
    main()
