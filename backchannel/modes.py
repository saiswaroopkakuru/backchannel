"""Compact active Claude Code prompt policy compiler (English-only Caveman + Ponytail + Graphify + Claude-Mem)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .analyzer import estimate_tokens
from .memory import build_memory_recall_snippet


def build_policy_prompt(
    config: dict[str, Any],
    *,
    cwd: str | Path | None = None,
    project: str = "",
    data_dir: str | Path | None = None,
    has_local_graph: bool | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    sections: list[str] = []

    voice = config.get("voice", "terse")
    if voice == "terse":
        sections.append(
            "[Voice: terse] Answer first, then reason, then next step. Omit greetings, pleasantries, hedging, "
            "and closing recaps. Keep code, commands, paths, numbers, errors, and negations verbatim. "
            "Use full prose for security warnings, irreversible actions, and code/docs persisted outside chat."
        )
    elif voice == "ultra":
        sections.append(
            "[Voice: ultra] Maximum brevity fragments; each technical fact once; drop articles where unambiguous. "
            "Zero ceremony. Keep code, paths, commands, errors, and negations exact. "
            "Plain prose for security warnings or irreversible confirmations."
        )
    elif voice == "megacave":
        sections.append(
            "[Voice: megacave] Extreme telegraphic English: drop all filler words, articles, pleasantries, "
            "auxiliary verbs; facts and code only; strictly English. Zero ceremony. Keep code blocks, commands, "
            "paths, identifiers, numbers, and error strings verbatim. Plain English for security warnings or "
            "irreversible confirmations."
        )

    minimalism = config.get("minimalism", "full")
    if minimalism == "lite":
        sections.append(
            "[Minimalism: lite] Reuse existing code, stdlib, and installed dependencies before adding new "
            "abstractions or packages. Keep security, validation, error handling, and accessibility intact."
        )
    elif minimalism == "full":
        sections.append(
            "[Minimalism: full] Before writing code, check in order: (1) already in codebase, (2) stdlib, "
            "(3) native platform feature, (4) existing dependency, (5) one-liner, (6) minimum new code. "
            "Never skip validation, error handling, security, or accessibility."
        )
    elif minimalism == "ultra":
        sections.append(
            "[Minimalism: ultra] Challenge whether the change needs to exist before editing. Follow the 7-step "
            "ladder (skip -> reuse -> stdlib -> platform -> existing dep -> one-liner -> minimum code). "
            "Preserve safety, error handling, and trust-boundary checks."
        )

    if config.get("graphAssist"):
        if has_local_graph is not None:
            has_graph = bool(has_local_graph)
        else:
            has_graph = bool(cwd and (Path(cwd) / ".backchannel" / "graph.json").exists())
        if has_graph:
            sections.append(
                "[Graphify] Local knowledge graph exists at .backchannel/graph.json. "
                "Call MCP tool `backchannel_graph_query` (or `backchannel graph query <symbol>`) "
                "before brute-force Grep/Glob scans."
            )
        elif preview:
            sections.append(
                "[Graphify] Enabled: when .backchannel/graph.json exists in a repo, Claude is routed "
                "to `backchannel_graph_query` before brute-force scanning."
            )

    memory_count = 0
    if config.get("memoryAssist"):
        recall = build_memory_recall_snippet(project, data_dir, 4)
        memory_count = recall["count"]
        if recall["text"]:
            sections.append(recall["text"])
        elif preview:
            sections.append(
                "[Claude-Mem] Enabled: recalls top project observations on SessionStart, exposes MCP "
                "`backchannel_memory_search`/`save`, and auto-summarizes sessions on SessionEnd."
            )

    text = "\n".join(sections)
    return {
        "text": text,
        "estimatedTokens": estimate_tokens(text) if text else 0,
        "memoryCount": memory_count,
        "activeEngines": {
            "backchannel": True,
            "caveman": voice != "off",
            "ponytail": minimalism != "off",
            "headroom": config.get("compression", "on") != "off",
            "graphify": bool(config.get("graphAssist")),
            "memory": bool(config.get("memoryAssist")),
        },
    }
