"""Backchannel chatter & multi-agent communication analyzer."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input": 15.0, "output": 75.0, "cacheRead": 1.5},
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cacheRead": 1.5},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cacheRead": 0.3},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cacheRead": 0.3},
    "claude-haiku-4": {"input": 0.8, "output": 4.0, "cacheRead": 0.08},
    "default": {"input": 3.0, "output": 15.0, "cacheRead": 0.3},
}

AGENT_HUES: list[int] = [152, 212, 34, 340, 276, 186]

_CEREMONY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:sure thing|sure|certainly|absolutely|of course|great question|good catch|happy to help|glad to help)\b[!.,]?",
            re.IGNORECASE,
        ),
        "pleasantry",
    ),
    (
        re.compile(
            r"\b(?:i'd be happy to|i would be happy to|thank you for|thanks for the|appreciate the)\b[^.!?\n]{0,28}",
            re.IGNORECASE,
        ),
        "pleasantry",
    ),
    (
        re.compile(
            r"\b(?:let me now|let me go ahead and|let me quickly|let me take a look at|i'll now|i will now|i am going to now|going ahead and|allow me to)\b",
            re.IGNORECASE,
        ),
        "preamble",
    ),
    (
        re.compile(
            r"\b(?:here is what i found|here's what i found|here are my findings|as requested|per your request|following up on your request)\b[:,]?",
            re.IGNORECASE,
        ),
        "preamble",
    ),
    (
        re.compile(
            r"\b(?:basically|essentially|actually|simply put|just wanted to|just to note|it seems like|it appears that|in order to|as a matter of fact)\b",
            re.IGNORECASE,
        ),
        "hedge",
    ),
    (
        re.compile(
            r"\b(?:hope this helps|let me know if you need(?: any(?:thing| further)[^.!?\n]{0,20})?|feel free to ask|please let me know|happy to dig deeper|to summarize|in summary|overall everything looks[^.!?\n]{0,24})\b[!.,]?",
            re.IGNORECASE,
        ),
        "closer",
    ),
    (
        re.compile(
            r"\b(?:i have carefully reviewed|i have thoroughly inspected|i have successfully completed|everything has been updated accordingly)\b[.,]?",
            re.IGNORECASE,
        ),
        "recap",
    ),
]

_PAYLOAD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"`[^`]+`"),
    re.compile(r"\b[\w./-]+\.(?:ts|tsx|js|mjs|cjs|py|go|rs|sql|json|md|sh|yml|yaml)\b(?::\d+)?"),
    re.compile(r"\bL\d+(?:-L?\d+)?\b"),
    re.compile(
        r"\b(?:HTTP\s+\d{3}|ERR_[A-Z_]+|ECONN\w+|SQLSTATE|exit\s+code\s+\d+|\d+\s*(?:ms|s|kb|mb|rows|tests?))\b",
        re.IGNORECASE,
    ),
]

_FENCE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def estimate_tokens(text: Any) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(str(text)) / 4))


def get_model_pricing(model: str | None) -> dict[str, float]:
    if not model:
        return MODEL_PRICING["default"]
    low = model.lower()
    for key, pricing in MODEL_PRICING.items():
        if key != "default" and key in low:
            return pricing
    return MODEL_PRICING["default"]


def compute_message_cost_usd(msg: dict[str, Any], model: str | None = None) -> float:
    pricing = get_model_pricing(msg.get("model") or model)
    in_cost = ((msg.get("inputTokens") or 0) / 1_000_000) * pricing["input"]
    out_cost = ((msg.get("outputTokens") or 0) / 1_000_000) * pricing["output"]
    cache_cost = ((msg.get("cacheReadTokens") or 0) / 1_000_000) * pricing["cacheRead"]
    return round(in_cost + out_cost + cache_cost, 4)


def analyze_message_text(text: str = "") -> dict[str, Any]:
    source = str(text or "")
    prose_only = _FENCE_BLOCK_RE.sub(" ", source)
    words = source.strip().split() if source.strip() else []
    word_count = len(words)

    matches: list[dict[str, Any]] = []
    for pat, category in _CEREMONY_PATTERNS:
        for m in pat.finditer(source):
            before = source[: m.start()]
            if before.count("```") % 2 == 1:
                continue
            phrase = m.group(0).strip()
            matches.append(
                {
                    "start": m.start(),
                    "end": m.end(),
                    "phrase": phrase,
                    "normalized": re.sub(r"[.,!:]+$", "", phrase.lower()),
                    "category": category,
                }
            )

    matches.sort(key=lambda item: (item["start"], -item["end"]))
    spans: list[dict[str, Any]] = []
    for item in matches:
        if not spans or item["start"] >= spans[-1]["end"]:
            spans.append(item)

    filler_words = sum(len(s["phrase"].split()) for s in spans)

    payload_hits = sum(len(pat.findall(source)) for pat in _PAYLOAD_PATTERNS)
    payload_hits += (source.count("```") // 2) * 3

    prose_words = len(prose_only.strip().split()) if prose_only.strip() else 0
    padding_words = round((prose_words - 55) * 0.25) if (prose_words > 55 and payload_hits == 0) else 0

    effective_filler = min(word_count, filler_words + padding_words)
    filler_pct = round((effective_filler / word_count) * 100, 1) if word_count > 0 else 0.0
    signal_pct = round(100.0 - filler_pct, 1)

    return {
        "wordCount": word_count,
        "fillerWords": effective_filler,
        "fillerPct": filler_pct,
        "signalPct": signal_pct,
        "payloadHits": payload_hits,
        "spans": spans,
    }


def classify_voice_style(avg_words: float, filler_pct: float, loop_count: int) -> str:
    if loop_count >= 2:
        return "looping"
    if filler_pct >= 22:
        return "ceremonial"
    if filler_pct >= 13 or avg_words > 82:
        return "chatty"
    if filler_pct < 7 and avg_words <= 36:
        return "terse"
    return "direct"


def _round2(val: float) -> float:
    return round(val + 1e-12, 2)


def analyze_session(raw_session: dict[str, Any]) -> dict[str, Any]:
    agents_map: dict[str, dict[str, Any]] = {}
    raw_agents = raw_session.get("agents") if isinstance(raw_session.get("agents"), list) else []

    for idx, a in enumerate(raw_agents):
        aid = a["id"]
        agents_map[aid] = {
            "id": aid,
            "name": a.get("name") or aid,
            "role": a.get("role") or "subagent",
            "model": a.get("model") or "claude-sonnet-4-6",
            "parentId": a.get("parentId"),
            "spawnDepth": a["spawnDepth"] if isinstance(a.get("spawnDepth"), (int, float)) else (0 if aid == "lead" else 1),
            "status": a.get("status") or "done",
            "hue": a["hue"] if isinstance(a.get("hue"), (int, float)) else AGENT_HUES[idx % len(AGENT_HUES)],
        }

    def ensure_agent(aid: str | None) -> None:
        if not aid or aid in ("user", "all") or aid in agents_map:
            return
        idx = len(agents_map)
        agents_map[aid] = {
            "id": aid,
            "name": aid,
            "role": "lead" if aid == "lead" else "subagent",
            "model": "claude-sonnet-4-6",
            "parentId": None if aid == "lead" else "lead",
            "spawnDepth": 0 if aid == "lead" else 1,
            "status": "done",
            "hue": AGENT_HUES[idx % len(AGENT_HUES)],
        }

    raw_messages = raw_session.get("messages") if isinstance(raw_session.get("messages"), list) else []
    for m in raw_messages:
        ensure_agent(m.get("fromAgentId"))
        ensure_agent(m.get("toAgentId"))

    messages: list[dict[str, Any]] = []
    for idx, m in enumerate(raw_messages):
        sender = agents_map.get(m.get("fromAgentId", ""))
        model = m.get("model") or (sender["model"] if sender else "claude-sonnet-4-6")
        text = m.get("text") or ""
        out_tok = int(m["outputTokens"]) if isinstance(m.get("outputTokens"), (int, float)) else estimate_tokens(text)
        in_tok = int(m["inputTokens"]) if isinstance(m.get("inputTokens"), (int, float)) else round(out_tok * 2.4)
        cache_tok = int(m["cacheReadTokens"]) if isinstance(m.get("cacheReadTokens"), (int, float)) else 0
        analysis = analyze_message_text(text)
        pricing = get_model_pricing(model)

        is_agent = m.get("fromAgentId") != "user"
        filler_tokens = round(out_tok * (analysis["fillerPct"] / 100.0)) if is_agent else 0
        cost_usd = (
            compute_message_cost_usd(
                {"inputTokens": in_tok, "outputTokens": out_tok, "cacheReadTokens": cache_tok, "model": model},
                model,
            )
            if is_agent
            else 0.0
        )
        chatter_tax = round((filler_tokens / 1_000_000) * pricing["output"], 4) if is_agent else 0.0

        messages.append(
            {
                "id": m.get("id") or f"m-{idx + 1}",
                "index": idx + 1,
                "timestamp": m.get("timestamp") or raw_session.get("startedAt") or iso_now(),
                "offsetSec": int(m["offsetSec"]) if isinstance(m.get("offsetSec"), (int, float)) else idx * 14,
                "fromAgentId": m.get("fromAgentId"),
                "toAgentId": m.get("toAgentId"),
                "kind": m.get("kind") or "reply",
                "toolName": m.get("toolName"),
                "model": model,
                "text": text,
                "inputTokens": in_tok,
                "outputTokens": out_tok,
                "cacheReadTokens": cache_tok,
                "totalTokens": in_tok + out_tok + cache_tok,
                "latencyMs": int(m["latencyMs"]) if isinstance(m.get("latencyMs"), (int, float)) else 1200,
                "costUsd": cost_usd,
                "fillerTokens": filler_tokens,
                "chatterTaxUsd": chatter_tax,
                "analysis": analysis,
            }
        )

    # Detect ping-pong loops (>= 4 alternating turns within 90s)
    pair_loops: dict[str, int] = {}
    for i in range(3, len(messages)):
        m0, m1, m2, m3 = messages[i - 3], messages[i - 2], messages[i - 1], messages[i]
        if (
            m0["fromAgentId"] != "user"
            and m1["fromAgentId"] != "user"
            and m0["fromAgentId"] == m2["fromAgentId"]
            and m1["fromAgentId"] == m3["fromAgentId"]
            and m0["toAgentId"] == m1["fromAgentId"]
            and m1["toAgentId"] == m0["fromAgentId"]
            and m2["toAgentId"] == m3["fromAgentId"]
            and m3["toAgentId"] == m2["fromAgentId"]
            and (m3["offsetSec"] - m0["offsetSec"]) <= 90
        ):
            pair_loops[m0["fromAgentId"]] = pair_loops.get(m0["fromAgentId"], 0) + 1
            pair_loops[m1["fromAgentId"]] = pair_loops.get(m1["fromAgentId"], 0) + 1

    agent_stats_map: dict[str, dict[str, Any]] = {}
    for aid, agent in agents_map.items():
        agent_stats_map[aid] = {
            **agent,
            "turns": 0,
            "received": 0,
            "words": 0,
            "fillerWords": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "cacheReadTokens": 0,
            "totalTokens": 0,
            "fillerTokens": 0,
            "rawCostUsd": 0.0,
            "rawChatterTaxUsd": 0.0,
            "totalLatencyMs": 0,
            "maxTurnWords": 0,
            "loopCount": pair_loops.get(aid, 0),
        }

    edges_map: dict[str, dict[str, Any]] = {}
    phrase_map: dict[str, dict[str, Any]] = {}

    for m in messages:
        frm = m["fromAgentId"]
        to = m["toAgentId"]
        if frm in agent_stats_map:
            s = agent_stats_map[frm]
            s["turns"] += 1
            s["words"] += m["analysis"]["wordCount"]
            s["fillerWords"] += m["analysis"]["fillerWords"]
            s["inputTokens"] += m["inputTokens"]
            s["outputTokens"] += m["outputTokens"]
            s["cacheReadTokens"] += m["cacheReadTokens"]
            s["totalTokens"] += m["totalTokens"]
            s["fillerTokens"] += m["fillerTokens"]
            s["rawCostUsd"] += m["costUsd"]
            s["rawChatterTaxUsd"] += m["chatterTaxUsd"]
            s["totalLatencyMs"] += m["latencyMs"]
            s["maxTurnWords"] = max(s["maxTurnWords"], m["analysis"]["wordCount"])

        if to == "all":
            for s in agent_stats_map.values():
                if s["id"] != frm:
                    s["received"] += 1
        elif to in agent_stats_map:
            agent_stats_map[to]["received"] += 1

        if frm != "user" and to != "user":
            targets = [aid for aid in agents_map if aid != frm] if to == "all" else [to]
            for target in targets:
                if target not in agents_map:
                    continue
                key = f"{frm}->{target}"
                if key not in edges_map:
                    edges_map[key] = {
                        "id": key,
                        "from": frm,
                        "to": target,
                        "messages": 0,
                        "outputTokens": 0,
                        "fillerTokens": 0,
                        "kinds": {},
                    }
                edge = edges_map[key]
                edge["messages"] += 1
                edge["outputTokens"] += m["outputTokens"]
                edge["fillerTokens"] += m["fillerTokens"]
                edge["kinds"][m["kind"]] = edge["kinds"].get(m["kind"], 0) + 1

        if frm != "user":
            for span in m["analysis"]["spans"]:
                pkey = span["normalized"]
                if pkey not in phrase_map:
                    phrase_map[pkey] = {
                        "phrase": span["phrase"],
                        "normalized": pkey,
                        "category": span["category"],
                        "count": 0,
                        "agents": set(),
                        "estTokens": 0,
                    }
                p = phrase_map[pkey]
                p["count"] += 1
                p["agents"].add(frm)
                p["estTokens"] += estimate_tokens(span["phrase"])

    agent_stats: list[dict[str, Any]] = []
    for s in agent_stats_map.values():
        avg_words = round(s["words"] / s["turns"]) if s["turns"] > 0 else 0
        if s["outputTokens"] > 0:
            filler_pct = round((s["fillerTokens"] / s["outputTokens"]) * 100, 1)
        elif s["words"] > 0:
            filler_pct = round((s["fillerWords"] / s["words"]) * 100, 1)
        else:
            filler_pct = 0.0
        signal_pct = round(100.0 - filler_pct, 1)
        avg_latency = round(s["totalLatencyMs"] / s["turns"]) if s["turns"] > 0 else 0
        cost_usd = _round2(s["rawCostUsd"])
        chatter_tax = _round2(s["rawChatterTaxUsd"])
        style = classify_voice_style(avg_words, filler_pct, s["loopCount"])

        agent_stats.append(
            {
                "id": s["id"],
                "name": s["name"],
                "role": s["role"],
                "model": s["model"],
                "parentId": s["parentId"],
                "spawnDepth": s["spawnDepth"],
                "status": s["status"],
                "hue": s["hue"],
                "turns": s["turns"],
                "received": s["received"],
                "words": s["words"],
                "avgWords": avg_words,
                "maxTurnWords": s["maxTurnWords"],
                "fillerWords": s["fillerWords"],
                "fillerPct": filler_pct,
                "signalPct": signal_pct,
                "inputTokens": s["inputTokens"],
                "outputTokens": s["outputTokens"],
                "cacheReadTokens": s["cacheReadTokens"],
                "totalTokens": s["totalTokens"],
                "fillerTokens": s["fillerTokens"],
                "costUsd": cost_usd,
                "chatterTaxUsd": chatter_tax,
                "avgLatencyMs": avg_latency,
                "loopCount": s["loopCount"],
                "style": style,
            }
        )
    agent_stats.sort(key=lambda a: a["outputTokens"], reverse=True)

    agent_messages = [m for m in messages if m["fromAgentId"] != "user"]
    inter_agent_messages = [m for m in messages if m["fromAgentId"] != "user" and m["toAgentId"] != "user"]
    total_words = sum(a["words"] for a in agent_stats)
    total_filler_words = sum(a["fillerWords"] for a in agent_stats)
    total_in = sum(a["inputTokens"] for a in agent_stats)
    total_out = sum(a["outputTokens"] for a in agent_stats)
    total_cache = sum(a["cacheReadTokens"] for a in agent_stats)
    total_tokens = total_in + total_out + total_cache
    total_filler_tok = sum(a["fillerTokens"] for a in agent_stats)
    total_cost = _round2(sum(a["costUsd"] for a in agent_stats))
    chatter_tax = _round2(sum(a["chatterTaxUsd"] for a in agent_stats))
    if total_out > 0:
        avg_filler_pct = round((total_filler_tok / total_out) * 100, 1)
    elif total_words > 0:
        avg_filler_pct = round((total_filler_words / total_words) * 100, 1)
    else:
        avg_filler_pct = 0.0
    signal_pct = round(100.0 - avg_filler_pct, 1)
    avg_latency_ms = round(sum(m["latencyMs"] for m in agent_messages) / len(agent_messages)) if agent_messages else 0

    duration_sec = 0
    if len(messages) == 1:
        duration_sec = max(1, round((messages[0]["latencyMs"] or 1000) / 1000))
    elif len(messages) > 1:
        for i in range(1, len(messages)):
            gap = max(0, messages[i]["offsetSec"] - messages[i - 1]["offsetSec"])
            duration_sec += min(gap, 120)
        duration_sec = max(1, duration_sec + round((messages[-1]["latencyMs"] or 0) / 1000))

    edges = sorted(edges_map.values(), key=lambda e: (e["messages"], e["outputTokens"]), reverse=True)
    top_phrases = sorted(
        [
            {
                "phrase": p["phrase"],
                "category": p["category"],
                "count": p["count"],
                "agents": sorted(p["agents"]),
                "estTokens": p["estTokens"],
            }
            for p in phrase_map.values()
        ],
        key=lambda p: (p["count"], p["estTokens"]),
        reverse=True,
    )[:12]

    speaking = [a for a in agent_stats if a["turns"] > 0]
    chattiest = max(speaking, key=lambda a: a["fillerPct"]) if speaking else None
    top_talker = agent_stats[0] if agent_stats else None

    finding = "No inter-agent exchanges recorded in this session yet."
    if chattiest and chattiest["fillerPct"] >= 15:
        ratio = f"{(chattiest['fillerPct'] / avg_filler_pct):.1f}" if avg_filler_pct > 0 else "1.0"
        finding = (
            f"{chattiest['name']} spent {chattiest['fillerPct']:.1f}% of its output on ceremony "
            f"across {chattiest['turns']} turns ({ratio}x session average, ${chattiest['chatterTaxUsd']:.2f} chatter tax)."
        )
    elif top_talker and agent_messages:
        share = f"{(top_talker['outputTokens'] / total_out) * 100:.0f}" if total_out > 0 else "0"
        finding = (
            f"{top_talker['name']} generated {share}% of agent output ({top_talker['outputTokens']:,} tokens) "
            f"while keeping {signal_pct:.1f}% signal across {len(agent_messages)} turns."
        )

    recommendations: list[dict[str, Any]] = []
    for agent in agent_stats:
        if agent["fillerPct"] >= 18:
            recommendations.append(
                {
                    "severity": "high",
                    "agentId": agent["id"],
                    "agentName": agent["name"],
                    "title": f"Tighten {agent['name']} output protocol",
                    "detail": (
                        f"{agent['fillerPct']:.1f}% filler across {agent['turns']} turns "
                        f"({agent['fillerTokens']:,} wasted output tokens). Add \"Answer first; omit pleasantries, "
                        "preambles, and recaps; cite path:line only.\" to its agent prompt."
                    ),
                }
            )
        elif agent["avgWords"] > 85:
            recommendations.append(
                {
                    "severity": "medium",
                    "agentId": agent["id"],
                    "agentName": agent["name"],
                    "title": f"Cap {agent['name']} handoff length",
                    "detail": (
                        f"Averaging {agent['avgWords']} words/turn (peak {agent['maxTurnWords']}). "
                        f"Ask {agent['name']} to return structured diff summaries instead of prose walkthroughs."
                    ),
                }
            )
        if agent["loopCount"] >= 2:
            recommendations.append(
                {
                    "severity": "medium",
                    "agentId": agent["id"],
                    "agentName": agent["name"],
                    "title": f"Break back-and-forth loop on {agent['name']}",
                    "detail": (
                        f"Detected {agent['loopCount']} rapid ping-pong exchanges. "
                        "Include acceptance criteria and exact file paths in the initial delegation."
                    ),
                }
            )

    if not recommendations and agent_messages:
        recommendations.append(
            {
                "severity": "low",
                "agentId": top_talker["id"] if top_talker else "lead",
                "agentName": top_talker["name"] if top_talker else "lead",
                "title": "Communication stayed disciplined",
                "detail": (
                    f"All {len(agent_stats)} agents kept filler under 18% "
                    f"with {signal_pct:.1f}% technical payload density."
                ),
            }
        )

    return {
        "id": raw_session["id"],
        "title": raw_session.get("title") or raw_session["id"],
        "project": raw_session.get("project") or "workspace",
        "source": raw_session.get("source") or "demo",
        "startedAt": raw_session.get("startedAt") or iso_now(),
        "isLive": bool(raw_session.get("isLive")),
        "finding": finding,
        "summary": {
            "agentCount": len(agent_stats),
            "totalMessages": len(messages),
            "agentTurns": len(agent_messages),
            "interAgentMessages": len(inter_agent_messages),
            "totalInputTokens": total_in,
            "totalOutputTokens": total_out,
            "totalCacheReadTokens": total_cache,
            "totalTokens": total_tokens,
            "totalFillerTokens": total_filler_tok,
            "totalCostUsd": total_cost,
            "chatterTaxUsd": chatter_tax,
            "avgFillerPct": avg_filler_pct,
            "signalPct": signal_pct,
            "avgLatencyMs": avg_latency_ms,
            "durationSec": duration_sec,
            "topTalkerId": top_talker["id"] if top_talker else None,
            "topTalkerName": top_talker["name"] if top_talker else None,
            "chattiestAgentId": chattiest["id"] if chattiest else None,
            "chattiestAgentName": chattiest["name"] if chattiest else None,
        },
        "agents": agent_stats,
        "edges": edges,
        "messages": messages,
        "topPhrases": top_phrases,
        "recommendations": recommendations,
    }


def summarize_portfolio(analyzed_sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sessions = analyzed_sessions or []
    projects = {s["project"] for s in sessions}
    total_messages = sum(s["summary"]["agentTurns"] for s in sessions)
    total_tokens = sum(s["summary"]["totalTokens"] for s in sessions)
    total_out = sum(s["summary"]["totalOutputTokens"] for s in sessions)
    total_filler = sum(s["summary"]["totalFillerTokens"] for s in sessions)
    total_cost = _round2(sum(s["summary"]["totalCostUsd"] for s in sessions))
    chatter_tax = _round2(sum(s["summary"]["chatterTaxUsd"] for s in sessions))
    duration_sec = sum(s["summary"]["durationSec"] for s in sessions)
    filler_pct = round((total_filler / total_out) * 100, 1) if total_out > 0 else 0.0
    signal_pct = round(100.0 - filler_pct, 1)

    by_name: dict[str, dict[str, Any]] = {}
    for session in sessions:
        for a in session["agents"]:
            row = by_name.setdefault(
                a["name"],
                {"name": a["name"], "turns": 0, "outputTokens": 0, "fillerTokens": 0, "costUsd": 0.0},
            )
            row["turns"] += a["turns"]
            row["outputTokens"] += a["outputTokens"]
            row["fillerTokens"] += a["fillerTokens"]
            row["costUsd"] = _round2(row["costUsd"] + a["costUsd"])

    top_agents = sorted(by_name.values(), key=lambda x: x["outputTokens"], reverse=True)[:4]
    return {
        "projectCount": len(projects),
        "sessionCount": len(sessions),
        "totalMessages": total_messages,
        "totalTokens": total_tokens,
        "totalOutputTokens": total_out,
        "totalFillerTokens": total_filler,
        "totalCostUsd": total_cost,
        "chatterTaxUsd": chatter_tax,
        "durationSec": duration_sec,
        "fillerPct": filler_pct,
        "signalPct": signal_pct,
        "topAgents": top_agents,
    }
