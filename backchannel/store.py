"""Read-only Claude Code JSONL transcript parser & live hook event store with semantic agent naming."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .analyzer import AGENT_HUES, analyze_session, estimate_tokens, iso_now
from .demo_data import get_demo_sessions


def get_default_paths() -> dict[str, Path]:
    home = Path.home()
    return {
        "dataDir": Path(os.environ.get("BACKCHANNEL_DATA_DIR") or (home / ".backchannel")),
        "claudeProjectsDir": Path(os.environ.get("BACKCHANNEL_CLAUDE_DIR") or (home / ".claude" / "projects")),
    }


def _read_json_lines(file_path: Path, max_bytes: int = 2 * 1024 * 1024) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []
    try:
        size = file_path.stat().st_size
        if size > max_bytes:
            with file_path.open("rb") as fh:
                fh.seek(size - max_bytes)
                raw = fh.read(max_bytes).decode("utf-8", errors="replace")
            nl = raw.find("\n")
            if nl >= 0:
                raw = raw[nl + 1 :]
        else:
            raw = file_path.read_text(encoding="utf-8", errors="replace")

        items: list[dict[str, Any]] = []
        for line in raw.splitlines():
            trimmed = line.strip()
            if not trimmed:
                continue
            try:
                obj = json.loads(trimmed)
                if isinstance(obj, dict):
                    items.append(obj)
            except Exception:
                pass
        return items
    except OSError:
        return []


def _extract_text(content: Any) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(p for p in parts if p).strip()
    return ""


def _clean_user_text(raw: Any) -> str:
    if not raw:
        return ""
    s = str(raw)
    for tag in (
        "system-reminder",
        "local-command-caveat",
        "command-name",
        "command-message",
        "command-args",
        "local-command-stdout",
    ):
        s = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _decode_project_dir_name(dir_name: str) -> str:
    parts = [p for p in dir_name.split("-") if p]
    return parts[-1] if parts else dir_name


def _is_noise_project_dir(dir_name: str) -> bool:
    low = dir_name.lower()
    return "observer-sessions" in low or "scratchpad" in low or low.endswith("system32")


def _parse_iso_ms(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000.0
    except Exception:
        return 0.0


def is_hex_or_machine_id(agent_id: Any) -> bool:
    if not agent_id or not isinstance(agent_id, str):
        return False
    clean = re.sub(r"^(?:agent-|sub-|subagent-)", "", agent_id, flags=re.I).strip()
    if re.fullmatch(r"[0-9a-f]{6,}", clean, re.I):
        return True
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}", clean, re.I):
        return True
    hex_chars = len(re.sub(r"[^0-9a-f]", "", clean, flags=re.I))
    return len(clean) >= 8 and (hex_chars / len(clean)) > 0.8


def infer_role_from_text(text: Any) -> str | None:
    if not text or not isinstance(text, str):
        return None
    s = text.lower()
    rules = [
        (r"\b(?:setup|getting your claude setup|working through backchannel)\b", "Setup Verifier"),
        (r"\b(?:omniroute|reverse proxy)\b", None),  # handled with guard below
        (r"\b(?:port\s*\d+|listening|bind|socket|network|localhost)\b", "Port Inspector"),
        (r"\b(?:watchdog|hang|heartbeat|freeze|timeout)\b", "Watchdog Fixer"),
        (r"\b(?:backchannel claude|launcher|launch|start claude)\b", "Claude Runner"),
        (r"\b(?:test|tests|passing|failing|assertion|unit|pytest|jest)\b", "Test Runner"),
        (r"\b(?:git|commit|diff|merge|branch|repo)\b", "Git Reviewer"),
        (r"\b(?:auth|jwt|token|redis|session|oauth)\b", "Auth Specialist"),
        (r"\b(?:database|sql|migration|schema|table|postgres|mongo)\b", "Database Specialist"),
        (r"\b(?:lint|eslint|prettier|typecheck|types|typescript)\b", "Type Inspector"),
        (r"\b(?:doc|docs|readme|markdown|documentation)\b", "Doc Specialist"),
        (r"\b(?:benchmark|perf|performance|latency|memory leak)\b", "Performance Auditor"),
        (r"\b(?:scrape|scraper|crawl|fetch|parser|extract)\b", "Data Extractor"),
        (r"\b(?:search|grep|find|locate|explore|codebase)\b", "Code Explorer"),
        (r"\b(?:refactor|clean|restructure|organize)\b", "Refactor Specialist"),
        (r"\b(?:build|bundle|compile|vite|webpack|tsc)\b", "Build Worker"),
    ]
    if re.search(r"\b(?:setup|getting your claude setup|working through backchannel)\b", s):
        return "Setup Verifier"
    if re.search(r"\b(?:omniroute|reverse proxy)\b", s) and re.search(r"\b(?:guard|bind|127|listen|security|fallback)\b", s):
        return "OmniRoute Guard"
    if re.search(r"\bomniroute\b", s):
        return "OmniRoute Specialist"
    for pat, label in rules[2:]:
        if label and re.search(pat, s):
            return label

    m = re.search(r"\b(check|inspect|verify|audit|fix|test|build|search|analyze)\s+(?:if\s+)?([a-z0-9_-]{3,15})", s)
    if m:
        verb, target = m.group(1), m.group(2)
        suffix = f"{verb[:-1]}er" if verb.endswith("e") else f"{verb}er"
        return f"{target.capitalize()} {suffix.capitalize()}"
    return None


def prettify_agent_name(
    agent_id: str | None,
    meta: dict[str, Any] | str | None = None,
    context_text: str = "",
    fallback_index: int = 0,
) -> str:
    if not agent_id:
        return "Agent"
    if agent_id == "lead":
        return "Lead"

    meta_dict = meta if isinstance(meta, dict) else {"role": meta} if isinstance(meta, str) else {}
    desc = meta_dict.get("description")
    if isinstance(desc, str) and desc.strip() and not is_hex_or_machine_id(desc.strip()):
        d = desc.strip()
        return f"{d[:18]}…" if len(d) > 20 else d

    role = meta_dict.get("role") or meta_dict.get("agentType")
    if isinstance(role, str) and role.lower() not in ("subagent", "general-purpose", "general") and not is_hex_or_machine_id(role):
        base = re.sub(r"[-_]+", " ", role).strip()
        return " ".join(w.capitalize() for w in base.split())

    inferred = infer_role_from_text(context_text or desc or meta_dict.get("text") or "")
    if inferred:
        return inferred

    if not is_hex_or_machine_id(agent_id):
        clean = re.sub(r"[-_]+", " ", re.sub(r"^agent-", "", str(agent_id))).strip()
        if clean and len(clean) <= 18:
            return " ".join(w.capitalize() for w in clean.split())

    idx = fallback_index if fallback_index > 0 else 1
    return f"Worker {idx}"


def parse_claude_transcript_file(session_file_path: str | Path, project_name: str = "workspace") -> dict[str, Any] | None:
    fpath = Path(session_file_path)
    session_id = fpath.stem
    rows = _read_json_lines(fpath)
    if not rows:
        return None

    try:
        file_mtime_iso = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        file_mtime_iso = iso_now()

    subagents_dir = fpath.parent / session_id / "subagents"
    sub_meta_by_id: dict[str, dict[str, Any]] = {}
    sub_id_by_tool_use_id: dict[str, str] = {}
    if subagents_dir.exists() and subagents_dir.is_dir():
        try:
            for meta_file in subagents_dir.glob("*.meta.json"):
                sub_id = meta_file.name[: -len(".meta.json")]
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    sub_meta_by_id[sub_id] = meta
                    if meta.get("toolUseId"):
                        sub_id_by_tool_use_id[meta["toolUseId"]] = sub_id
                except Exception:
                    pass
        except OSError:
            pass

    agents_map: dict[str, dict[str, Any]] = {
        "lead": {
            "id": "lead",
            "name": "Lead",
            "role": "orchestrator",
            "model": "claude-sonnet-4-6",
            "parentId": None,
            "spawnDepth": 0,
            "status": "done",
            "hue": AGENT_HUES[0],
        }
    }

    messages: list[dict[str, Any]] = []
    title = ""
    last_valid_ts = next((r["timestamp"] for r in rows if r.get("timestamp")), file_mtime_iso)

    def ensure_agent(aid: str | None, meta: dict[str, Any] | None = None) -> None:
        if not aid or aid in ("user", "all"):
            return
        meta = meta or {}
        saved = sub_meta_by_id.get(aid) or sub_meta_by_id.get(f"agent-{aid}") or {}
        merged = {
            "role": meta.get("role") or saved.get("agentType") or "subagent",
            "description": meta.get("description") or saved.get("description"),
            "model": meta.get("model") or saved.get("pickedEffortModel") or "claude-sonnet-4-6",
            "spawnDepth": meta["spawnDepth"] if isinstance(meta.get("spawnDepth"), int) else (saved.get("spawnDepth") or 1),
        }
        if aid not in agents_map:
            idx = len(agents_map)
            agents_map[aid] = {
                "id": aid,
                "name": prettify_agent_name(aid, merged, meta.get("contextText", ""), idx),
                "role": merged["role"],
                "model": merged["model"],
                "parentId": None if aid == "lead" else "lead",
                "spawnDepth": 0 if aid == "lead" else merged["spawnDepth"],
                "status": "done",
                "hue": AGENT_HUES[idx % len(AGENT_HUES)],
            }
        else:
            existing = agents_map[aid]
            if meta.get("model"):
                existing["model"] = meta["model"]
            if is_hex_or_machine_id(existing["name"]) or re.match(r"^Worker\s*\d+$", existing["name"], re.I):
                better = prettify_agent_name(aid, merged, meta.get("contextText", ""), list(agents_map.keys()).index(aid))
                if better and not re.match(r"^Worker\s*\d+$", better, re.I):
                    existing["name"] = better

    def push_msg(item: dict[str, Any]) -> None:
        nonlocal last_valid_ts
        ts = item.get("timestamp") or last_valid_ts
        if item.get("timestamp"):
            last_valid_ts = item["timestamp"]
        messages.append({**item, "timestamp": ts})

    tool_use_by_id: dict[str, dict[str, Any]] = {}
    seen_delegations: set[str] = set()

    for row in rows:
        if not isinstance(row, dict) or (row.get("type") not in ("user", "assistant") and not row.get("message")):
            continue
        ts = row.get("timestamp") or last_valid_ts
        if row.get("timestamp"):
            last_valid_ts = row["timestamp"]
        msg = row.get("message") or {}
        usage = msg.get("usage") or row.get("usage") or {}
        model = msg.get("model") or row.get("model") or "claude-sonnet-4-6"

        if row.get("type") == "user" or msg.get("role") == "user":
            content = msg.get("content") if msg.get("content") is not None else row.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        origin = tool_use_by_id.get(block.get("tool_use_id", ""))
                        if origin:
                            reply_text = _extract_text(block.get("content"))
                            raw_agent = (row.get("toolUseResult") or {}).get("agentId") if isinstance(row.get("toolUseResult"), dict) else None
                            sub_agent_id = (
                                (f"agent-{raw_agent}" if raw_agent and f"agent-{raw_agent}" in sub_meta_by_id else raw_agent)
                                or origin["targetId"]
                            )
                            ensure_agent(sub_agent_id, {"role": origin["targetRole"], "contextText": reply_text})
                            if reply_text:
                                push_msg(
                                    {
                                        "id": row.get("uuid") or f"tr-{len(messages) + 1}",
                                        "timestamp": ts,
                                        "fromAgentId": sub_agent_id,
                                        "toAgentId": "lead",
                                        "kind": "peer" if origin["toolName"] == "SendMessage" else "reply",
                                        "toolName": origin["toolName"],
                                        "model": model,
                                        "text": reply_text[:2400],
                                        "inputTokens": usage.get("input_tokens") or estimate_tokens(reply_text) * 2,
                                        "outputTokens": usage.get("output_tokens") or estimate_tokens(reply_text),
                                        "cacheReadTokens": usage.get("cache_read_input_tokens") or 0,
                                    }
                                )
                    elif block.get("type") == "text" and block.get("text") and not row.get("isMeta"):
                        cleaned = _clean_user_text(block["text"])
                        if not cleaned:
                            continue
                        if not title:
                            title = cleaned[:72]
                        push_msg(
                            {
                                "id": row.get("uuid") or f"u-{len(messages) + 1}",
                                "timestamp": ts,
                                "fromAgentId": "user",
                                "toAgentId": "lead",
                                "kind": "delegation",
                                "text": cleaned[:1200],
                                "inputTokens": 0,
                                "outputTokens": estimate_tokens(cleaned),
                                "cacheReadTokens": 0,
                            }
                        )
            elif isinstance(content, str) and content.strip() and not row.get("isMeta"):
                cleaned = _clean_user_text(content)
                if cleaned:
                    if not title:
                        title = cleaned[:72]
                    push_msg(
                        {
                            "id": row.get("uuid") or f"u-{len(messages) + 1}",
                            "timestamp": ts,
                            "fromAgentId": "user",
                            "toAgentId": "lead",
                            "kind": "delegation",
                            "text": cleaned[:1200],
                            "inputTokens": 0,
                            "outputTokens": estimate_tokens(cleaned),
                            "cacheReadTokens": 0,
                        }
                    )
        elif row.get("type") == "assistant" or msg.get("role") == "assistant":
            ensure_agent("lead", {"model": model})
            content = msg.get("content") if msg.get("content") is not None else row.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
            plain_parts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tname = block.get("name") or ""
                    inp = block.get("input") or {}
                    if tname in ("Agent", "Task", "SendMessage", "TeamCreate", "TaskCreate", "TaskUpdate"):
                        matched_sub = sub_id_by_tool_use_id.get(block.get("id", ""))
                        target_id = matched_sub or str(
                            inp.get("recipient")
                            or inp.get("agent_id")
                            or inp.get("subagent_type")
                            or inp.get("name")
                            or f"sub-{len(tool_use_by_id) + 1}"
                        )
                        target_role = inp.get("subagent_type") or inp.get("role") or "subagent"
                        body = inp.get("message") or inp.get("prompt") or inp.get("description") or inp.get("subject") or json.dumps(inp)
                        ensure_agent(target_id, {"role": target_role, "description": inp.get("description"), "contextText": str(body)})
                        if block.get("id"):
                            tool_use_by_id[block["id"]] = {"toolName": tname, "targetId": target_id, "targetRole": target_role}
                        seen_delegations.add(target_id)
                        push_msg(
                            {
                                "id": block.get("id") or f"tu-{len(messages) + 1}",
                                "timestamp": ts,
                                "fromAgentId": "lead",
                                "toAgentId": "all" if tname == "TaskCreate" else target_id,
                                "kind": "peer" if tname == "SendMessage" else ("broadcast" if tname == "TaskCreate" else "delegation"),
                                "toolName": tname,
                                "model": model,
                                "text": str(body)[:2400],
                                "inputTokens": usage.get("input_tokens") or 0,
                                "outputTokens": usage.get("output_tokens") or estimate_tokens(body),
                                "cacheReadTokens": usage.get("cache_read_input_tokens") or 0,
                            }
                        )
                elif block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                    plain_parts.append(block["text"].strip())
            if plain_parts:
                joined = "\n".join(plain_parts)
                push_msg(
                    {
                        "id": row.get("uuid") or f"a-{len(messages) + 1}",
                        "timestamp": ts,
                        "fromAgentId": "lead",
                        "toAgentId": "user",
                        "kind": "reply",
                        "model": model,
                        "text": joined[:2400],
                        "inputTokens": usage.get("input_tokens") or 0,
                        "outputTokens": usage.get("output_tokens") or estimate_tokens(joined),
                        "cacheReadTokens": usage.get("cache_read_input_tokens") or 0,
                    }
                )

    if subagents_dir.exists() and subagents_dir.is_dir():
        try:
            for sub_file in subagents_dir.glob("*.jsonl"):
                sub_id = sub_file.stem
                meta = sub_meta_by_id.get(sub_id) or {}
                sub_rows = _read_json_lines(sub_file, max_bytes=512 * 1024)
                ensure_agent(
                    sub_id,
                    {
                        "role": meta.get("agentType") or meta.get("role") or "subagent",
                        "description": meta.get("description"),
                        "model": meta.get("pickedEffortModel"),
                        "spawnDepth": meta.get("spawnDepth") or 1,
                    },
                )
                saw_prompt = sub_id in seen_delegations
                sub_last_ts = next((r["timestamp"] for r in sub_rows if r.get("timestamp")), last_valid_ts)
                for r in sub_rows:
                    msg = r.get("message") or {}
                    r_ts = r.get("timestamp") or sub_last_ts
                    if r.get("timestamp"):
                        sub_last_ts = r["timestamp"]
                    if not saw_prompt and (r.get("type") == "user" or msg.get("role") == "user"):
                        prompt_txt = _clean_user_text(_extract_text(msg.get("content")))
                        if prompt_txt:
                            saw_prompt = True
                            ensure_agent(sub_id, {"contextText": prompt_txt})
                            push_msg(
                                {
                                    "id": r.get("uuid") or f"subp-{len(messages) + 1}",
                                    "timestamp": r_ts,
                                    "fromAgentId": "lead",
                                    "toAgentId": sub_id,
                                    "kind": "delegation",
                                    "toolName": "Agent",
                                    "model": agents_map["lead"]["model"],
                                    "text": prompt_txt[:1800],
                                    "inputTokens": estimate_tokens(prompt_txt),
                                    "outputTokens": estimate_tokens(prompt_txt),
                                    "cacheReadTokens": 0,
                                }
                            )
                    elif r.get("type") == "assistant" or msg.get("role") == "assistant":
                        txt = _extract_text(msg.get("content"))
                        if not txt:
                            continue
                        u = msg.get("usage") or {}
                        m = msg.get("model") or meta.get("pickedEffortModel") or "claude-haiku-4-5"
                        ensure_agent(sub_id, {"model": m, "contextText": txt})
                        push_msg(
                            {
                                "id": r.get("uuid") or f"sub-{len(messages) + 1}",
                                "timestamp": r_ts,
                                "fromAgentId": sub_id,
                                "toAgentId": "lead",
                                "kind": "reply",
                                "toolName": "Subagent",
                                "model": m,
                                "text": txt[:2400],
                                "inputTokens": u.get("input_tokens") or 0,
                                "outputTokens": u.get("output_tokens") or estimate_tokens(txt),
                                "cacheReadTokens": u.get("cache_read_input_tokens") or 0,
                            }
                        )
        except OSError:
            pass

    if not messages:
        return None
    messages.sort(key=lambda m: _parse_iso_ms(m.get("timestamp")))

    base_ms = _parse_iso_ms(messages[0].get("timestamp")) or (time.time() * 1000.0)
    prev_ms = base_ms
    for idx, m in enumerate(messages):
        cur_ms = _parse_iso_ms(m.get("timestamp")) or prev_ms
        m["offsetSec"] = max(0, round((cur_ms - base_ms) / 1000.0))
        delta = 1200 if idx == 0 else min(25_000, max(250, round(cur_ms - prev_ms)))
        m["latencyMs"] = 0 if m["fromAgentId"] == "user" else delta
        prev_ms = cur_ms

    return {
        "id": f"cc-{session_id[:12]}",
        "title": title or f"Claude Code session {session_id[:8]}",
        "project": project_name or "workspace",
        "source": "claude-jsonl",
        "startedAt": messages[0]["timestamp"],
        "agents": list(agents_map.values()),
        "messages": messages,
    }


def _clean_agent_names(agents_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    fallback = 1
    out = list(agents_map.values())
    for a in out:
        if is_hex_or_machine_id(a["name"]) or re.fullmatch(r"[0-9a-f]{6,}", str(a["name"]), re.I):
            a["name"] = f"Worker {fallback}"
            fallback += 1
    return out


def build_sessions_from_hook_events(events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    events = events or []
    grouped: dict[str, dict[str, Any]] = {}
    agent_text_by_session: dict[str, dict[str, list[str]]] = {}

    for ev in events:
        if not isinstance(ev, dict) or not ev.get("sessionId"):
            continue
        sid = ev["sessionId"]
        m = agent_text_by_session.setdefault(sid, {})
        for candidate in (ev.get("fromAgent"), ev.get("toAgent"), ev.get("agentId")):
            if candidate and candidate not in ("lead", "user", "all") and ev.get("text"):
                m.setdefault(candidate, []).append(str(ev["text"]))

    for ev in events:
        if not isinstance(ev, dict) or not ev.get("sessionId"):
            continue
        sid = ev["sessionId"]
        if sid not in grouped:
            grouped[sid] = {
                "id": f"hook-{sid}",
                "title": f"Live hook session ({ev.get('project') or 'workspace'})",
                "project": ev.get("project") or "workspace",
                "source": "hooks",
                "isLive": True,
                "startedAt": ev.get("timestamp") or iso_now(),
                "agentsMap": {
                    "lead": {
                        "id": "lead",
                        "name": "Lead",
                        "role": "orchestrator",
                        "model": ev.get("model") or "claude-sonnet-4-6",
                        "parentId": None,
                        "spawnDepth": 0,
                        "status": "speaking",
                        "hue": AGENT_HUES[0],
                    }
                },
                "messages": [],
            }
        sess = grouped[sid]
        sess_texts = agent_text_by_session.get(sid, {})

        def register(aid: str | None, role: str | None) -> None:
            if not aid or aid in ("user", "all"):
                return
            ctx = " ".join(sess_texts.get(aid, []))
            amap = sess["agentsMap"]
            if aid not in amap:
                idx = len(amap)
                ev_name = ev.get("eventName")
                status = "done" if ev_name == "SubagentStop" else ("idle" if ev_name == "TeammateIdle" else "speaking")
                amap[aid] = {
                    "id": aid,
                    "name": prettify_agent_name(aid, {"role": role}, ctx, idx),
                    "role": role or "subagent",
                    "model": ev.get("model") or "claude-sonnet-4-6",
                    "parentId": None if aid == "lead" else "lead",
                    "spawnDepth": 0 if aid == "lead" else 1,
                    "status": status,
                    "hue": AGENT_HUES[idx % len(AGENT_HUES)],
                }
            else:
                a = amap[aid]
                ev_name = ev.get("eventName")
                if ev_name in ("SubagentStop", "SessionEnd"):
                    a["status"] = "done"
                elif ev_name == "TeammateIdle":
                    a["status"] = "idle"
                elif ev.get("fromAgent") == aid:
                    a["status"] = "speaking"
                if ctx and (is_hex_or_machine_id(a["name"]) or re.match(r"^Worker\s*\d+$", a["name"], re.I)):
                    better = prettify_agent_name(aid, {"role": a["role"]}, ctx, list(amap.keys()).index(aid))
                    if better and not re.match(r"^Worker\s*\d+$", better, re.I):
                        a["name"] = better

        register(ev.get("fromAgent"), ev.get("agentType"))
        register(ev.get("toAgent"), ev.get("agentType"))

        if ev.get("eventName") == "UserPromptSubmit" and ev.get("text") and sess["title"].startswith("Live hook session"):
            cleaned = _clean_user_text(ev["text"])
            if cleaned:
                sess["title"] = cleaned[:72]

        if ev.get("text") and ev.get("eventName") not in ("SessionStart", "SessionEnd"):
            base_ms = _parse_iso_ms(sess["startedAt"]) or (time.time() * 1000.0)
            ev_ms = _parse_iso_ms(ev.get("timestamp")) or (time.time() * 1000.0)
            out_tok = estimate_tokens(ev["text"])
            sess["messages"].append(
                {
                    "id": ev.get("id") or f"he-{len(sess['messages']) + 1}",
                    "timestamp": ev.get("timestamp") or iso_now(),
                    "offsetSec": max(0, round((ev_ms - base_ms) / 1000.0)),
                    "fromAgentId": ev.get("fromAgent") or "lead",
                    "toAgentId": ev.get("toAgent") or "lead",
                    "kind": ev.get("kind") or "event",
                    "toolName": ev.get("toolName") or ev.get("eventName"),
                    "model": ev.get("model") or "claude-sonnet-4-6",
                    "text": ev["text"],
                    "inputTokens": 0 if ev.get("fromAgent") == "user" else out_tok * 3,
                    "outputTokens": out_tok,
                    "cacheReadTokens": 0,
                    "latencyMs": 950,
                }
            )

    for sess in grouped.values():
        counts: dict[str, int] = {}
        for a in sess["agentsMap"].values():
            counts[a["name"]] = counts.get(a["name"], 0) + 1
        seen: dict[str, int] = {}
        for a in sess["agentsMap"].values():
            if counts[a["name"]] > 1 and a["id"] != "lead":
                seen[a["name"]] = seen.get(a["name"], 0) + 1
                a["name"] = f"{a['name']} {seen[a['name']]}"

    return [
        {
            "id": s["id"],
            "title": s["title"],
            "project": s["project"],
            "source": s["source"],
            "isLive": s["isLive"],
            "startedAt": s["startedAt"],
            "agents": _clean_agent_names(s["agentsMap"]),
            "messages": s["messages"],
        }
        for s in grouped.values()
        if s["messages"]
    ]


class BackchannelStore:
    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        claude_projects_dir: str | Path | None = None,
        demo: bool = False,
        max_transcript_sessions: int = 20,
    ) -> None:
        defaults = get_default_paths()
        self.data_dir = Path(data_dir) if data_dir else defaults["dataDir"]
        self.claude_projects_dir = Path(claude_projects_dir) if claude_projects_dir else defaults["claudeProjectsDir"]
        self.force_demo = bool(demo)
        self.max_transcript_sessions = max_transcript_sessions
        self.events_file = self.data_dir / "events.jsonl"
        self.live_hook_events: list[dict[str, Any]] = []
        self.simulated_sessions: dict[str, dict[str, Any]] = {}
        self._transcript_cache: dict[str, Any] = {"at": 0.0, "items": []}
        self._file_parse_cache: dict[str, tuple[float, int, dict[str, Any] | None]] = {}
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self.reload()

    def on_update(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def _emit_update(self, payload: dict[str, Any]) -> None:
        for cb in list(self._listeners):
            try:
                cb(payload)
            except Exception:
                pass

    def reload(self) -> None:
        self.live_hook_events = _read_json_lines(self.events_file)

    def scan_claude_transcripts(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if not force and (now - self._transcript_cache["at"]) < 10.0:
            return self._transcript_cache["items"]
        if not self.claude_projects_dir.exists():
            self._transcript_cache = {"at": now, "items": []}
            return []

        candidates: list[dict[str, Any]] = []
        try:
            for proj_dir in self.claude_projects_dir.iterdir():
                if not proj_dir.is_dir() or _is_noise_project_dir(proj_dir.name):
                    continue
                try:
                    jsonl_files = list(proj_dir.glob("*.jsonl"))
                except OSError:
                    continue
                for f in jsonl_files:
                    sub_dir = proj_dir / f.stem / "subagents"
                    sub_count = 0
                    if sub_dir.exists() and sub_dir.is_dir():
                        try:
                            sub_count = sum(1 for _ in sub_dir.glob("*.jsonl"))
                        except OSError:
                            pass
                    try:
                        st = f.stat()
                        candidates.append(
                            {
                                "full": f,
                                "mtime": st.st_mtime,
                                "size": st.st_size,
                                "subagentCount": sub_count,
                                "project": _decode_project_dir_name(proj_dir.name),
                            }
                        )
                    except OSError:
                        pass
        except OSError:
            return []

        multi = sorted([c for c in candidates if c["subagentCount"] > 0], key=lambda c: c["mtime"], reverse=True)
        other = sorted([c for c in candidates if c["subagentCount"] == 0], key=lambda c: c["mtime"], reverse=True)
        ordered = (multi + other)[: self.max_transcript_sessions]

        parsed: list[dict[str, Any]] = []
        for c in ordered:
            key = str(c["full"])
            cached = self._file_parse_cache.get(key)
            if cached and cached[0] == c["mtime"] and cached[1] == c["size"]:
                sess = cached[2]
            else:
                sess = parse_claude_transcript_file(c["full"], c["project"])
                self._file_parse_cache[key] = (c["mtime"], c["size"], sess)
            if sess:
                parsed.append(sess)
        self._transcript_cache = {"at": now, "items": parsed}
        return parsed

    def record_hook_event(self, event: dict[str, Any]) -> None:
        self.live_hook_events.append(event)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.events_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass
        self._emit_update({"type": "hook", "event": event})

    def upsert_simulated_session(self, raw_session: dict[str, Any]) -> None:
        self.simulated_sessions[raw_session["id"]] = raw_session
        self._emit_update({"type": "simulation", "sessionId": raw_session["id"]})

    def get_sessions(self, mode: str = "auto") -> dict[str, Any]:
        hook_sessions = build_sessions_from_hook_events(self.live_hook_events)
        transcript_sessions = [] if self.force_demo else self.scan_claude_transcripts()
        real_sessions = hook_sessions + transcript_sessions
        sim_sessions = list(self.simulated_sessions.values())
        demo_sessions = get_demo_sessions()

        if mode == "demo" or self.force_demo:
            chosen = sim_sessions + demo_sessions
            active_source = "demo"
        elif mode == "live":
            chosen = list(real_sessions)
            active_source = "live"
        elif real_sessions:
            chosen = sim_sessions + real_sessions
            active_source = "live"
        else:
            chosen = sim_sessions + demo_sessions
            active_source = "demo"

        analyzed = [analyze_session(s) for s in chosen]
        analyzed.sort(
            key=lambda s: (
                1 if s["isLive"] else 0,
                1 if len(s["agents"]) > 1 else 0,
                _parse_iso_ms(s.get("startedAt")),
            ),
            reverse=True,
        )

        return {
            "activeSource": active_source,
            "counts": {
                "live": len(real_sessions),
                "hooks": len(hook_sessions),
                "transcripts": len(transcript_sessions),
                "demo": len(demo_sessions) + len(sim_sessions),
            },
            "sessions": analyzed,
        }

    def get_diagnostics(self) -> dict[str, Any]:
        transcripts = [] if self.force_demo else self.scan_claude_transcripts()
        return {
            "dataDir": str(self.data_dir),
            "eventsFile": str(self.events_file),
            "eventsExists": self.events_file.exists(),
            "hookEventCount": len(self.live_hook_events),
            "claudeProjectsDir": str(self.claude_projects_dir),
            "claudeExists": self.claude_projects_dir.exists(),
            "transcriptSessionCount": len(transcripts),
        }
