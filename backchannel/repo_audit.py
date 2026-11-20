"""Ponytail-style deterministic repo-wide minimalism & dead-code auditor."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .analyzer import iso_now
from .graphify import build_knowledge_graph

REPLACEABLE_NPM_DEPS: dict[str, str] = {
    "node-fetch": "Native global fetch() in Node 18+.",
    "isomorphic-fetch": "Native global fetch() in Node 18+.",
    "cross-fetch": "Native global fetch() in Node 18+.",
    "axios": "Native fetch() covers standard HTTP requests with zero dependency overhead.",
    "uuid": "Native crypto.randomUUID() in Node 14.17+ and all modern browsers.",
    "lodash": "Native Array/Object/Set/Map methods or targeted 3-line helpers.",
    "underscore": "Native ES2023 Array/Object methods.",
    "moment": "Native Intl.DateTimeFormat or lightweight date math (moment is deprecated).",
    "chalk": "Native util.styleText() in Node 20.12+ or simple ANSI codes.",
    "left-pad": "Native String.prototype.padStart().",
    "rimraf": "Native fs.rmSync(dir, { recursive: true, force: true }).",
    "mkdirp": "Native fs.mkdirSync(dir, { recursive: true }).",
    "glob": "Native fs.globSync() in Node 22+ or simple fs.readdirSync recursion.",
    "dotenv": "Native node --env-file=.env in Node 20.6+.",
}

REPLACEABLE_PY_DEPS: dict[str, str] = {
    "six": "Python 3 native syntax; six is only for Python 2 compatibility.",
    "pathlib2": "Standard library pathlib is built into Python 3.",
    "typing-extensions": "Check if stdlib typing already covers your target Python 3.10+ version.",
    "tomli": "Standard library tomllib is built into Python 3.11+.",
    "mock": "Standard library unittest.mock is built into Python 3.",
}

_ENTRY_RE = re.compile(
    r"(?:^|/)(?:__init__|__main__|index|main|app|server|cli|bin|hook|mcp)\."
    r"|(?:^|/)(?:bin|scripts|test|tests|__tests__|ui)/|\.test\.|\.spec\.|test_[^/]+\.py$",
    re.IGNORECASE,
)


def run_repo_audit(target_dir: str | Path) -> dict[str, Any]:
    abs_root = Path(target_dir).resolve()
    graph = build_knowledge_graph(abs_root, persist=False)
    findings: list[dict[str, Any]] = []

    # 1a. package.json replaceable dependency check
    pkg_path = abs_root / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            all_deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
            for dep in all_deps:
                if dep in REPLACEABLE_NPM_DEPS:
                    findings.append(
                        {
                            "category": "redundant-dep",
                            "severity": "medium",
                            "location": "package.json",
                            "title": f"Replaceable dependency: {dep}",
                            "detail": REPLACEABLE_NPM_DEPS[dep],
                        }
                    )
        except Exception:
            pass

    # 1b. pyproject.toml / requirements.txt replaceable Python dependency check
    for dep_file in ("pyproject.toml", "requirements.txt"):
        dp = abs_root / dep_file
        if dp.exists():
            try:
                raw_dep_txt = dp.read_text(encoding="utf-8", errors="ignore").lower()
                for dep, hint in REPLACEABLE_PY_DEPS.items():
                    if re.search(rf"(?:^|[\"'\\s]){re.escape(dep)}(?:[\"'=<>!~,\s]|$)", raw_dep_txt, re.M):
                        findings.append(
                            {
                                "category": "redundant-dep",
                                "severity": "medium",
                                "location": dep_file,
                                "title": f"Replaceable dependency: {dep}",
                                "detail": hint,
                            }
                        )
            except OSError:
                pass

    code_nodes = [n for n in graph["nodes"] if n["kind"] == "code"]
    contents: dict[str, str] = {}
    for n in code_nodes:
        try:
            contents[n["id"]] = (abs_root / n["id"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    # 2. Orphan non-entry code modules
    for n in code_nodes:
        if n["inDegree"] == 0 and not _ENTRY_RE.search(n["id"]):
            findings.append(
                {
                    "category": "orphan-module",
                    "severity": "low",
                    "location": n["id"],
                    "title": f"Unreferenced module: {n['label']}",
                    "detail": f"{n['id']} ({n['lines']} lines) has 0 local importers. Confirm it is an external entrypoint or remove dead code.",
                }
            )

    # 3. Oversized monolith files (> 600 LOC)
    for n in code_nodes:
        if n["lines"] > 600:
            findings.append(
                {
                    "category": "monolith-file",
                    "severity": "medium",
                    "location": n["id"],
                    "title": f"Large file ({n['lines']} lines): {n['label']}",
                    "detail": f"Check if {n['id']} mixes unrelated responsibilities that could be trimmed or split.",
                }
            )

    # 4. Potentially unused exported symbols across code files
    unused_checked = 0
    js_export_re = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M)
    py_def_re = re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z][A-Za-z0-9_]{3,})", re.M)
    for n in code_nodes:
        if _ENTRY_RE.search(n["id"]):
            continue
        src = contents.get(n["id"], "")
        pat = py_def_re if n["ext"] == ".py" else js_export_re
        for m in pat.finditer(src):
            if unused_checked >= 200:
                break
            sym = m.group(1)
            if not sym or len(sym) < 4 or sym.startswith("_"):
                continue
            unused_checked += 1
            sym_re = re.compile(rf"\b{re.escape(sym)}\b")
            used_elsewhere = any(
                other_id != n["id"] and sym_re.search(txt) for other_id, txt in contents.items()
            )
            if not used_elsewhere:
                findings.append(
                    {
                        "category": "unused-export",
                        "severity": "low",
                        "location": n["id"],
                        "title": f"Exported symbol only used locally: {sym}",
                        "detail": f"{sym} in {n['id']} is defined/exported publicly but never referenced by any other indexed file.",
                    }
                )

    by_sev = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    penalty = by_sev["high"] * 15 + by_sev["medium"] * 6 + by_sev["low"] * 2
    score = max(0, min(100, 100 - penalty))

    return {
        "project": graph["project"],
        "rootDir": str(abs_root),
        "auditedAt": iso_now(),
        "filesScanned": len(code_nodes),
        "score": score,
        "counts": {"total": len(findings), **by_sev},
        "findings": findings[:40],
    }
