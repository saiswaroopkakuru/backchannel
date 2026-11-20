"""Zero-dependency unified MCP JSON-RPC 2.0 stdio server for backchannel (13 native tools)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .analyzer import summarize_portfolio
from .compressor import (
    compress_tool_output,
    compute_headroom_summary,
    load_savings_ledger,
    record_compression_saving,
)
from .config import load_config, save_config
from .doc_compress import compress_markdown_file
from .graphify import build_knowledge_graph, extract_pdf_facts, load_knowledge_graph, query_knowledge_graph
from .memory import add_memory, delete_memory, load_memories, search_memories, summarize_session_to_memory
from .modes import build_policy_prompt
from .repo_audit import run_repo_audit
from .store import BackchannelStore

SERVER_INFO = {"name": "backchannel", "version": __version__}
PROTOCOL_VERSION = "2024-11-05"

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "backchannel_memory_search",
        "description": "Hybrid BM25 + semantic search across persistent Claude-Mem cross-session observations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms, symbol, error, or concept"},
                "project": {"type": "string", "description": "Optional project name filter"},
                "kind": {"type": "string", "enum": ["all", "decision", "bugfix", "pattern", "preference", "gotcha", "summary"]},
                "limit": {"type": "number", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "backchannel_memory_save",
        "description": "Save a concise cross-session observation (bugfix, decision, pattern, preference, gotcha) to Claude-Mem.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short 1-line summary headline"},
                "body": {"type": "string", "description": "Concrete technical details with path:line citations"},
                "project": {"type": "string", "description": 'Project name (or "global")'},
                "kind": {"type": "string", "enum": ["decision", "bugfix", "pattern", "preference", "gotcha", "summary"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "backchannel_memory_timeline",
        "description": "Return recent chronological Claude-Mem observations for a project or globally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "limit": {"type": "number", "description": "Max entries (default 12)"},
            },
        },
    },
    {
        "name": "backchannel_memory_delete",
        "description": "Delete a stale or obsolete observation from Claude-Mem by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Memory ID to delete"}},
            "required": ["id"],
        },
    },
    {
        "name": "backchannel_session_summarize",
        "description": "Generate a zero-API-cost structured handoff summary of the latest or specified Claude Code session and save it to Claude-Mem.",
        "inputSchema": {
            "type": "object",
            "properties": {"sessionId": {"type": "string", "description": "Optional session ID (defaults to latest)"}},
        },
    },
    {
        "name": "backchannel_graph_query",
        "description": "Query the local Graphify codebase knowledge graph (.backchannel/graph.json) for matching files, symbols, PageRank hubs, and 1-hop import neighbors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symbol, filename, or module keyword"},
                "dir": {"type": "string", "description": "Project root directory (defaults to cwd)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "backchannel_graph_build",
        "description": "Build or refresh the deterministic local Graphify knowledge graph (16+ languages + PDFs) at .backchannel/graph.json.",
        "inputSchema": {
            "type": "object",
            "properties": {"dir": {"type": "string", "description": "Project root directory (defaults to cwd)"}},
        },
    },
    {
        "name": "backchannel_compress_log",
        "description": "Headroom log compressor: strip ANSI, collapse passing tests/duplicates/stack internals while preserving every failure verbatim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Raw verbose log or tool output to compress"},
                "mode": {"type": "string", "enum": ["on", "aggressive"]},
                "label": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "backchannel_compress_doc",
        "description": "Caveman markdown compressor: tighten CLAUDE.md or markdown docs while keeping code blocks, paths, tables, and negations exact (auto-creates .bak.md).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to markdown file"},
                "dryRun": {"type": "boolean", "description": "Preview without modifying file"},
            },
            "required": ["filePath"],
        },
    },
    {
        "name": "backchannel_repo_audit",
        "description": "Run a Ponytail repo-wide minimalism audit detecting replaceable dependencies, orphan modules, unused exports, and oversized monoliths.",
        "inputSchema": {
            "type": "object",
            "properties": {"dir": {"type": "string", "description": "Project root directory (defaults to cwd)"}},
        },
    },
    {
        "name": "backchannel_mode",
        "description": "Read or update active Caveman voice (off/terse/ultra/megacave), Ponytail minimalism (off/lite/full/ultra), Headroom compression, Graphify, or Claude-Mem settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "voice": {"type": "string", "enum": ["off", "terse", "ultra", "megacave"]},
                "minimalism": {"type": "string", "enum": ["off", "lite", "full", "ultra"]},
                "compression": {"type": "string", "enum": ["off", "on", "aggressive"]},
                "graphAssist": {"type": "boolean"},
                "memoryAssist": {"type": "boolean"},
            },
        },
    },
    {
        "name": "backchannel_chatter_status",
        "description": "Inspect recent Claude Code multi-agent chatter ratio, token cost, Headroom 5h/7d budget windows, and active modes.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "backchannel_extract_doc",
        "description": "Extract clean readable text/markdown locally from a PDF, HTML, or Markdown file with zero external dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to local .pdf, .html, .htm, or .md file"},
                "maxChars": {"type": "number", "description": "Maximum characters to return (default 12000)"},
            },
            "required": ["filePath"],
        },
    },
]


def _extract_html_text(html: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", str(html or ""), flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"</(?:p|div|li|h[1-6]|tr|br)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def handle_tool_call(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    data_dir: str | Path | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    args = args or {}
    work_dir = Path(args.get("dir") or cwd or os.getcwd()).resolve()

    if name == "backchannel_memory_search":
        items = search_memories(
            query=args.get("query") or "",
            project=args.get("project") or "",
            kind=args.get("kind") or "all",
            limit=min(30, int(args.get("limit") or 10)),
            override_dir=data_dir,
        )
        return {
            "count": len(items),
            "items": [
                {k: m.get(k) for k in ("id", "project", "kind", "title", "body", "tags", "score", "createdAt")}
                for m in items
            ],
        }

    if name == "backchannel_memory_save":
        entry = add_memory(
            {
                "title": args.get("title"),
                "body": args.get("body"),
                "project": args.get("project") or work_dir.name,
                "kind": args.get("kind") or "pattern",
                "tags": args.get("tags") or [],
                "source": "mcp",
            },
            data_dir,
        )
        return {"saved": True, "entry": entry}

    if name == "backchannel_memory_timeline":
        all_mems = load_memories(data_dir)
        proj = str(args.get("project") or "").lower()
        filtered = (
            [m for m in all_mems if str(m.get("project", "")).lower() == proj or m.get("project") == "global"]
            if proj
            else all_mems
        )
        limit = min(30, int(args.get("limit") or 12))
        return {
            "count": len(filtered),
            "items": [
                {k: m.get(k) for k in ("id", "createdAt", "project", "kind", "title", "body")}
                for m in filtered[:limit]
            ],
        }

    if name == "backchannel_memory_delete":
        deleted = delete_memory(str(args.get("id") or ""), data_dir)
        return {"deleted": deleted, "id": args.get("id")}

    if name == "backchannel_session_summarize":
        store = BackchannelStore(data_dir=data_dir)
        sessions = store.get_sessions("auto")["sessions"]
        sess = next((s for s in sessions if s["id"] == args.get("sessionId")), None) if args.get("sessionId") else (sessions[0] if sessions else None)
        if not sess:
            return {"summarized": False, "reason": "No sessions found"}
        entry = summarize_session_to_memory(sess, data_dir)
        return {"summarized": True, "sessionId": sess["id"], "entry": entry}

    if name == "backchannel_graph_query":
        graph = load_knowledge_graph(work_dir) or build_knowledge_graph(work_dir, persist=True)
        res = query_knowledge_graph(graph, args.get("query") or "")
        return {
            "project": graph["project"],
            "compressionRatio": graph["stats"]["compressionRatio"],
            "matches": [
                {
                    "id": m["id"],
                    "cluster": m.get("cluster") or m.get("community"),
                    "rank": m.get("rank"),
                    "inDegree": m.get("inDegree"),
                    "outDegree": m.get("outDegree"),
                    "symbols": m["matchedSymbols"] if m.get("matchedSymbols") else (m.get("symbols") or [])[:8],
                    "importedBy": m.get("importedBy") or [],
                    "importsLocal": m.get("importsLocal") or [],
                }
                for m in res["matches"]
            ],
        }

    if name == "backchannel_graph_build":
        graph = build_knowledge_graph(work_dir, persist=True)
        return {
            "project": graph["project"],
            "stats": graph["stats"],
            "hubs": graph["hubs"],
            "communities": graph["communities"],
        }

    if name == "backchannel_compress_log":
        mode = args.get("mode") or load_config(data_dir).get("compression") or "on"
        res = compress_tool_output(args.get("text") or "", mode=mode)
        if res["savedTokens"] > 0:
            record_compression_saving(
                {"source": "mcp:compress_log", "label": args.get("label") or "mcp log", "mode": mode, **res},
                data_dir,
            )
        return res

    if name == "backchannel_compress_doc":
        return compress_markdown_file(args["filePath"], write=not bool(args.get("dryRun")))

    if name == "backchannel_repo_audit":
        return run_repo_audit(work_dir)

    if name == "backchannel_mode":
        patch = {
            k: args[k]
            for k in ("voice", "minimalism", "compression", "graphAssist", "memoryAssist")
            if k in args and args[k] is not None
        }
        cfg = save_config(patch, data_dir) if patch else load_config(data_dir)
        return {"config": cfg, "policy": build_policy_prompt(cfg, cwd=work_dir, data_dir=data_dir, preview=True)}

    if name == "backchannel_chatter_status":
        store = BackchannelStore(data_dir=data_dir)
        res = store.get_sessions("auto")
        cfg = load_config(data_dir)
        ledger = load_savings_ledger(data_dir)
        return {
            "activeSource": res["activeSource"],
            "config": cfg,
            "portfolio": summarize_portfolio(res["sessions"]),
            "headroom": compute_headroom_summary(res["sessions"], ledger, cfg),
            "latestFinding": res["sessions"][0]["finding"] if res["sessions"] else None,
        }

    if name == "backchannel_extract_doc":
        abs_path = Path(args["filePath"]).resolve()
        ext = abs_path.suffix.lower()
        max_chars = min(40_000, int(args.get("maxChars") or 12_000))
        if ext == ".pdf":
            pdf = extract_pdf_facts(abs_path.read_bytes())
            return {"filePath": str(abs_path), "kind": "pdf", "headings": pdf["symbols"], "text": pdf["text"][:max_chars]}
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
        text = _extract_html_text(raw) if ext in (".html", ".htm") else raw
        return {"filePath": str(abs_path), "kind": ext.lstrip(".") or "text", "text": text[:max_chars]}

    raise ValueError(f"Unknown MCP tool: {name}")


def handle_jsonrpc_message(
    msg: dict[str, Any] | None,
    *,
    data_dir: str | Path | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return None
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO},
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
        if method == "tools/call":
            data = handle_tool_call(
                str(params.get("name") or ""),
                params.get("arguments") or {},
                data_dir=data_dir,
                cwd=cwd,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]},
            }
        if req_id is not None:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return None
    except Exception as exc:
        if req_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]},
        }


def run_stdio_server() -> None:
    for line in sys.stdin:
        trimmed = line.strip()
        if not trimmed:
            continue
        try:
            res = handle_jsonrpc_message(json.loads(trimmed))
            if res is not None:
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
        except Exception:
            pass


if __name__ == "__main__":
    run_stdio_server()
