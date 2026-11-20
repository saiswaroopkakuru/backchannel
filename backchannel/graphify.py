"""Graphify v3 zero-dependency local codebase & document knowledge graph engine."""

from __future__ import annotations

import json
import os
import posixpath
import re
import zlib
from collections import deque
from pathlib import Path
from typing import Any

from .analyzer import estimate_tokens, iso_now

IGNORED_DIRS: set[str] = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".cache",
    ".venv",
    "venv",
    "__pycache__",
    "target",
    ".backchannel",
    ".taste-skill",
    "vendor",
    "out",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    "*.egg-info",
}

CODE_EXTS: set[str] = {
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".py", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".swift", ".sql", ".md", ".json", ".yml", ".yaml", ".toml", ".pdf",
}


def extract_pdf_facts(raw_bytes: bytes) -> dict[str, Any]:
    """Pure-Python lightweight PDF text & heading extractor (plain + FlateDecode streams)."""
    latin = raw_bytes.decode("latin-1", errors="ignore")
    chunks: list[str] = []
    title_match = re.search(r"/Title\s*\(([^)]{1,120})\)", latin)
    if title_match:
        chunks.append(title_match.group(1))

    def extract_tj(s: str) -> list[str]:
        out: list[str] = []
        for m in re.finditer(r"\(([^()\\]{3,160})\)\s*Tj", s):
            out.append(m.group(1))
        for m in re.finditer(r"\[([^\]]{4,400})\]\s*TJ", s):
            inner = "".join(re.findall(r"\(([^()\\]{1,120})\)", m.group(1))).strip()
            if len(inner) >= 3:
                out.append(inner)
        return out

    scanned = 0
    for m in re.finditer(r"stream\r?\n([\s\S]{1,120000}?)\r?\nendstream", latin):
        if scanned >= 12:
            break
        scanned += 1
        stream_str = m.group(1)
        decoded = stream_str
        try:
            decoded = zlib.decompress(stream_str.encode("latin-1")).decode("latin-1", errors="ignore")
        except Exception:
            pass
        chunks.extend(extract_tj(decoded))

    text = re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7E\n]+", " ", " ".join(chunks))).strip()
    headings: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        clean = re.sub(r"[^\x20-\x7E]+", " ", c).strip()
        if 4 <= len(clean) <= 64 and re.search(r"[A-Za-z]{3,}", clean) and clean not in seen:
            seen.add(clean)
            headings.append(clean)
            if len(headings) >= 12:
                break
    return {"text": text, "symbols": headings}


def _walk_files(root_dir: Path, max_files: int = 600) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    queue: deque[Path] = deque([root_dir])
    while queue and len(results) < max_files:
        cur = queue.popleft()
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for ent in entries:
            if len(results) >= max_files:
                break
            name = ent.name
            if name.startswith(".") and name not in (".claude-plugin", ".mcp.json"):
                continue
            if ent.is_dir(follow_symlinks=False):
                if name not in IGNORED_DIRS and not name.endswith(".egg-info"):
                    queue.append(Path(ent.path))
            elif ent.is_file(follow_symlinks=False):
                ext = Path(name).suffix.lower()
                if ext in CODE_EXTS:
                    try:
                        size = ent.stat(follow_symlinks=False).st_size
                        limit = 2 * 1024 * 1024 if ext == ".pdf" else 350 * 1024
                        if size <= limit:
                            rel = Path(ent.path).relative_to(root_dir).as_posix()
                            results.append({"full": Path(ent.path), "rel": rel, "ext": ext, "size": size})
                    except OSError:
                        pass
    return results


def _extract_file_facts(ext: str, content: str) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    symbols: list[str] = []

    def add_sym(sym: str | None) -> None:
        if sym and sym not in symbols and len(symbols) < 20:
            symbols.append(sym)

    if ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
        for m in re.finditer(r"(?:import\s+(?:[\s\S]*?from\s+)?|require\s*\(\s*|export\s+[\s\S]*?from\s+)['\"]([^'\"]+)['\"]", content):
            imports.append(m.group(1))
        for m in re.finditer(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)"
            r"|^\s*export\s+(?:const|let|var|type|interface|enum)\s+([A-Za-z_$][\w$]*)",
            content,
            re.M,
        ):
            add_sym(m.group(1) or m.group(2))
    elif ext == ".py":
        for m in re.finditer(r"^\s*(?:from\s+(\.{1,3}[\w.]*|[\w.]+)\s+import|import\s+([\w.]+))", content, re.M):
            imports.append(m.group(1) or m.group(2))
        for m in re.finditer(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", content, re.M):
            add_sym(m.group(1))
    elif ext == ".go":
        for m in re.finditer(r'"([\w./-]+)"', content[:1800]):
            imports.append(m.group(1))
        for m in re.finditer(r"^\s*(?:func\s+(?:\([^)]+\)\s*)?|type\s+)([A-Za-z_]\w*)", content, re.M):
            add_sym(m.group(1))
    elif ext == ".rs":
        for m in re.finditer(r"^\s*(?:pub\s+)?(?:use|mod)\s+([\w:]+)", content, re.M):
            imports.append(m.group(1).replace("::", "/"))
        for m in re.finditer(r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_]\w*)", content, re.M):
            add_sym(m.group(1))
    elif ext in (".java", ".kt", ".cs", ".swift"):
        for m in re.finditer(r"^\s*(?:import|using)\s+([\w.]+)", content, re.M):
            imports.append(m.group(1))
        for m in re.finditer(
            r"^\s*(?:public|private|protected|internal|open|data|sealed|abstract|final|\s)*"
            r"(?:class|interface|struct|enum|record|object|fun|func)\s+([A-Za-z_]\w*)",
            content,
            re.M,
        ):
            add_sym(m.group(1))
    elif ext in (".c", ".h", ".cpp", ".hpp"):
        for m in re.finditer(r'^\s*#include\s+"([^"]+)"', content, re.M):
            imports.append(f"./{m.group(1)}")
        for m in re.finditer(r"^\s*(?:struct|class|enum)\s+([A-Za-z_]\w*)", content, re.M):
            add_sym(m.group(1))
    elif ext in (".rb", ".php"):
        for m in re.finditer(r"(?:require_relative|require|include)\s*\(?\s*['\"]([^'\"]+)['\"]", content):
            imports.append(m.group(1))
        for m in re.finditer(r"^\s*(?:class|module|def|function)\s+([A-Za-z_]\w*)", content, re.M):
            add_sym(m.group(1))
    elif ext == ".sql":
        for m in re.finditer(r"CREATE\s+(?:TABLE|VIEW|INDEX|FUNCTION)\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?([\w.]+)[`\"']?", content, re.I):
            add_sym(m.group(1))
    elif ext == ".md":
        for m in re.finditer(r"^#{1,2}\s+(.+)$", content, re.M):
            add_sym(m.group(1).strip()[:48])

    dedup_imports = list(dict.fromkeys(imports))
    return dedup_imports, symbols


def _resolve_import(from_rel: str, spec: str, file_set: set[str]) -> str | None:
    if not spec:
        return None
    if spec.startswith("."):
        base_dir = posixpath.dirname(from_rel)
        # Handle Python relative imports like ".config" or "..lib.config"
        if not spec.startswith("./") and not spec.startswith("../"):
            dots = len(spec) - len(spec.lstrip("."))
            rest = spec[dots:].replace(".", "/")
            up = "/".join([".."] * max(0, dots - 1))
            joined = posixpath.normpath(posixpath.join(base_dir, up, rest)) if rest else posixpath.normpath(posixpath.join(base_dir, up))
            for cand in (f"{joined}.py", f"{joined}/__init__.py"):
                if cand in file_set:
                    return cand
            return None
        raw = posixpath.normpath(posixpath.join(base_dir, spec))
        candidates = [
            raw,
            f"{raw}.mjs", f"{raw}.js", f"{raw}.ts", f"{raw}.tsx", f"{raw}.jsx", f"{raw}.py", f"{raw}.json",
            f"{raw}/index.mjs", f"{raw}/index.js", f"{raw}/index.ts", f"{raw}/__init__.py",
        ]
        for c in candidates:
            if c in file_set:
                return c
        return None

    as_path = spec.replace(".", "/")
    for cand in (f"{as_path}.py", f"{as_path}/__init__.py", f"{as_path}.rs", f"{as_path}/mod.rs"):
        if cand in file_set:
            return cand
    return None


def _run_graph_algorithms(nodes_map: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    adj: dict[str, list[str]] = {nid: [] for nid in nodes_map}
    in_adj: dict[str, list[str]] = {nid: [] for nid in nodes_map}
    for e in edges:
        if e["from"] in adj and e["to"] in adj:
            adj[e["from"]].append(e["to"])
            adj[e["to"]].append(e["from"])
            in_adj[e["to"]].append(e["from"])

    label = {nid: n["community"] for nid, n in nodes_map.items()}
    for _ in range(6):
        changed = False
        for nid, neighbors in adj.items():
            if len(neighbors) < 2:
                continue
            counts: dict[str, float] = {label[nid]: 1.2}
            for nb in neighbors:
                lbl = label[nb]
                counts[lbl] = counts.get(lbl, 0.0) + 1.0
            best = max(counts.items(), key=lambda kv: kv[1])[0]
            if best != label[nid]:
                label[nid] = best
                changed = True
        if not changed:
            break

    n_nodes = max(1, len(nodes_map))
    rank = {nid: 1.0 / n_nodes for nid in nodes_map}
    out_deg: dict[str, int] = {}
    for e in edges:
        out_deg[e["from"]] = out_deg.get(e["from"], 0) + 1

    for _ in range(10):
        nxt = {}
        for nid in nodes_map:
            total = sum(rank[src] / max(1, out_deg.get(src, 1)) for src in in_adj[nid])
            nxt[nid] = 0.15 / n_nodes + 0.85 * total
        rank = nxt

    for nid, node in nodes_map.items():
        node["cluster"] = label.get(nid) or node["community"]
        node["rank"] = round(rank.get(nid, 0.0) * n_nodes, 2)


def build_knowledge_graph(
    target_dir: str | Path, *, persist: bool = True, max_files: int = 600
) -> dict[str, Any]:
    abs_root = Path(target_dir).resolve()
    if not abs_root.exists() or not abs_root.is_dir():
        raise FileNotFoundError(f"Directory not found: {abs_root}")

    files = _walk_files(abs_root, max_files=max_files)
    file_set = {f["rel"] for f in files}
    nodes_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    raw_bytes = 0

    for f in files:
        try:
            if f["ext"] == ".pdf":
                pdf = extract_pdf_facts(f["full"].read_bytes())
                imports, symbols = [], pdf["symbols"]
                lines = max(1, round(len(pdf["text"]) / 80))
                raw_bytes += len(pdf["text"]) or f["size"]
            else:
                content = f["full"].read_text(encoding="utf-8", errors="replace")
                imports, symbols = _extract_file_facts(f["ext"], content)
                lines = len(content.splitlines()) or 1
                raw_bytes += f["size"]
        except OSError:
            continue

        parts = f["rel"].split("/")
        community = parts[0] if len(parts) > 1 else "root"
        ext = f["ext"]
        if ext in (".md", ".pdf"):
            kind = "doc"
        elif ext in (".json", ".yml", ".yaml", ".toml"):
            kind = "config"
        elif ext == ".sql":
            kind = "schema"
        else:
            kind = "code"

        nodes_map[f["rel"]] = {
            "id": f["rel"],
            "label": posixpath.basename(f["rel"]),
            "community": community,
            "cluster": community,
            "kind": kind,
            "ext": ext,
            "bytes": f["size"],
            "lines": lines,
            "symbols": symbols,
            "imports": imports,
            "inDegree": 0,
            "outDegree": 0,
            "rank": 1.0,
        }

    edge_keys: set[str] = set()
    for node in nodes_map.values():
        for spec in node["imports"]:
            target = _resolve_import(node["id"], spec, file_set)
            if target and target != node["id"]:
                ekey = f"{node['id']}->{target}"
                if ekey not in edge_keys:
                    edge_keys.add(ekey)
                    edges.append({"from": node["id"], "to": target, "kind": "imports"})
                    node["outDegree"] += 1
                    nodes_map[target]["inDegree"] += 1

    _run_graph_algorithms(nodes_map, edges)

    nodes = sorted(
        [{**n, "degree": n["inDegree"] + n["outDegree"]} for n in nodes_map.values()],
        key=lambda n: (n["degree"], n["rank"], len(n["symbols"])),
        reverse=True,
    )

    comm_map: dict[str, dict[str, Any]] = {}
    for n in nodes:
        ckey = n.get("cluster") or n["community"]
        c = comm_map.setdefault(
            ckey, {"name": ckey, "files": 0, "symbols": 0, "internalEdges": 0, "bytes": 0}
        )
        c["files"] += 1
        c["symbols"] += len(n["symbols"])
        c["bytes"] += n["bytes"]

    for e in edges:
        c1 = nodes_map.get(e["from"], {}).get("cluster")
        c2 = nodes_map.get(e["to"], {}).get("cluster")
        if c1 and c1 == c2 and c1 in comm_map:
            comm_map[c1]["internalEdges"] += 1

    communities = sorted(comm_map.values(), key=lambda c: c["files"], reverse=True)

    raw_repo_tokens = max(1, round(raw_bytes / 4))
    digest_lines = [
        f"{n['id']} [{n['cluster']}] ({', '.join(n['symbols'][:6])})" for n in nodes
    ] + [f"{e['from']} -> {e['to']}" for e in edges]
    graph_tokens = max(1, estimate_tokens("\n".join(digest_lines)))
    compression_ratio = round(raw_repo_tokens / graph_tokens, 1)
    total_symbols = sum(len(n["symbols"]) for n in nodes)
    pdf_count = sum(1 for n in nodes if n["ext"] == ".pdf")

    graph = {
        "version": 2,
        "project": abs_root.name,
        "rootDir": str(abs_root),
        "builtAt": iso_now(),
        "stats": {
            "fileCount": len(nodes),
            "symbolCount": total_symbols,
            "edgeCount": len(edges),
            "communityCount": len(communities),
            "pdfCount": pdf_count,
            "rawRepoTokens": raw_repo_tokens,
            "graphTokens": graph_tokens,
            "compressionRatio": compression_ratio,
        },
        "communities": communities,
        "hubs": [
            {
                "id": n["id"],
                "label": n["label"],
                "community": n["cluster"],
                "inDegree": n["inDegree"],
                "outDegree": n["outDegree"],
                "degree": n["degree"],
                "rank": n["rank"],
                "symbols": n["symbols"][:5],
            }
            for n in nodes[:8]
        ],
        "nodes": nodes,
        "edges": edges,
    }

    if persist:
        out_dir = abs_root / ".backchannel"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
        except OSError:
            pass

    return graph


def load_knowledge_graph(target_dir: str | Path) -> dict[str, Any] | None:
    file_path = Path(target_dir).resolve() / ".backchannel" / "graph.json"
    if not file_path.exists():
        return None
    try:
        parsed = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or parsed.get("version") != 2:
            return None
        return parsed
    except Exception:
        return None


def query_knowledge_graph(graph: dict[str, Any] | None, query: str = "") -> dict[str, Any]:
    if not graph or not isinstance(graph.get("nodes"), list):
        return {"query": query, "matches": [], "neighborhoodEdges": []}
    q = str(query or "").strip().lower()
    if not q:
        return {
            "query": "",
            "matches": graph["nodes"][:12],
            "neighborhoodEdges": graph["edges"][:24],
        }

    terms = [t for t in q.split() if len(t) >= 2] or [q]
    scored: list[dict[str, Any]] = []
    for n in graph["nodes"]:
        score = 0.0
        id_low = n["id"].lower()
        cluster_low = str(n.get("cluster") or n.get("community") or "").lower()
        sym_hits: list[str] = []
        for term in terms:
            if term in id_low:
                score += 8 if id_low.endswith(term) else 5
            if term in cluster_low:
                score += 2
            for s in n.get("symbols") or []:
                if term in s.lower():
                    score += 4
                    if s not in sym_hits:
                        sym_hits.append(s)
        if score > 0:
            scored.append({**n, "matchedSymbols": sym_hits, "score": score + (n.get("rank") or 0) * 0.5})

    scored.sort(key=lambda x: (x["score"], x.get("degree", 0)), reverse=True)
    top = scored[:12]
    top_ids = {n["id"] for n in top}
    neighborhood_edges = [e for e in graph["edges"] if e["from"] in top_ids or e["to"] in top_ids]
    matches = [
        {
            **m,
            "importedBy": [e["from"] for e in graph["edges"] if e["to"] == m["id"]],
            "importsLocal": [e["to"] for e in graph["edges"] if e["from"] == m["id"]],
        }
        for m in top
    ]
    return {"query": query, "matches": matches, "neighborhoodEdges": neighborhood_edges}
