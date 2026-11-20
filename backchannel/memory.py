"""Claude-Mem v3 persistent cross-session memory engine (hybrid BM25 + 3-gram cosine search)."""

from __future__ import annotations

import json
import math
import random
import re
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .analyzer import estimate_tokens, iso_now
from .config import get_data_dir

MEMORY_KINDS: tuple[str, ...] = ("decision", "bugfix", "pattern", "preference", "gotcha", "summary")


def get_memories_path(override_dir: str | Path | None = None) -> Path:
    return get_data_dir(override_dir) / "memories.jsonl"


def _tokenize(text: str | None) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9_./:-]+", " ", str(text or "").lower())
    return [w for w in cleaned.split() if len(w) >= 2]


def _char_trigrams(text: str | None) -> dict[str, int]:
    norm = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip() + " "
    counts: dict[str, int] = {}
    for i in range(max(0, len(norm) - 2)):
        g = norm[i : i + 3]
        counts[g] = counts.get(g, 0) + 1
    return counts


def _cosine_sim(map_a: dict[str, int], map_b: dict[str, int]) -> float:
    if not map_a or not map_b:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    for k, v in map_a.items():
        norm_a += v * v
        bv = map_b.get(k)
        if bv:
            dot += v * bv
    norm_b = sum(v * v for v in map_b.values())
    if not norm_a or not norm_b:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _ts_key(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def load_memories(override_dir: str | Path | None = None) -> list[dict[str, Any]]:
    path = get_memories_path(override_dir)
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("id") and not obj.get("deleted"):
                    items.append(obj)
            except Exception:
                pass
    except Exception:
        return []
    items.sort(key=lambda m: _ts_key(m.get("createdAt")), reverse=True)
    return items


def _write_all_memories(items: list[dict[str, Any]], override_dir: str | Path | None = None) -> None:
    data_dir = get_data_dir(override_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(m) for m in items) + ("\n" if items else "")
    get_memories_path(override_dir).write_text(body, encoding="utf-8")


def add_memory(data: dict[str, Any], override_dir: str | Path | None = None) -> dict[str, Any]:
    title = str(data.get("title") or "").strip()
    body = str(data.get("body") or data.get("content") or title).strip()
    if not body:
        raise ValueError("Memory content cannot be empty")

    project = str(data.get("project") or "global").strip() or "global"
    kind = data.get("kind") if data.get("kind") in MEMORY_KINDS else "pattern"
    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(t).strip().lower() for t in raw_tags if str(t).strip()][:8]
    else:
        tags = [t.strip().lower() for t in str(raw_tags or "").split(",") if t.strip()][:8]

    existing = load_memories(override_dir)
    norm_body = re.sub(r"\s+", " ", body.lower())[:160]
    for m in existing:
        if m.get("project") == project and re.sub(r"\s+", " ", str(m.get("body", "")).lower())[:160] == norm_body:
            return m

    ts_b36 = format(int(time.time() * 1000), "x")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    entry = {
        "id": f"mem-{ts_b36}-{rand}",
        "createdAt": iso_now(),
        "project": project,
        "kind": kind,
        "title": (title or re.split(r"[.\n]", body)[0])[:96],
        "body": body[:900],
        "tags": tags,
        "source": data.get("source") or "manual",
        "tokens": estimate_tokens(body),
    }

    data_dir = get_data_dir(override_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with get_memories_path(override_dir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def delete_memory(mem_id: str, override_dir: str | Path | None = None) -> bool:
    existing = load_memories(override_dir)
    nxt = [m for m in existing if m.get("id") != mem_id]
    if len(nxt) == len(existing):
        return False
    _write_all_memories(nxt, override_dir)
    return True


def search_memories(
    *,
    query: str = "",
    project: str = "",
    kind: str = "",
    limit: int = 20,
    override_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    all_items = load_memories(override_dir)
    proj_low = str(project or "").lower()
    candidates = [
        m
        for m in all_items
        if (not kind or kind == "all" or m.get("kind") == kind)
        and (
            not proj_low
            or proj_low == "all"
            or str(m.get("project", "")).lower() == proj_low
            or m.get("project") == "global"
        )
    ]

    q_terms = _tokenize(query)
    if not q_terms:
        return [
            {**m, "score": 2 if str(m.get("project", "")).lower() == proj_low else 1}
            for m in candidates[:limit]
        ]

    docs = []
    for m in candidates:
        full = f"{m.get('title', '')} {m.get('body', '')} {m.get('project', '')} {m.get('kind', '')} {' '.join(m.get('tags') or [])}"
        docs.append({"m": m, "tokens": _tokenize(full), "trigrams": _char_trigrams(full)})

    avg_len = sum(len(d["tokens"]) for d in docs) / max(1, len(docs))
    df: dict[str, int] = {}
    for term in q_terms:
        df[term] = sum(
            1 for d in docs if any(term in tok or tok in term for tok in d["tokens"])
        )

    q_tri = _char_trigrams(query)
    n_docs = len(docs)
    k1, b = 1.5, 0.75

    scored: list[dict[str, Any]] = []
    for d in docs:
        bm25 = 0.0
        dl = len(d["tokens"]) or 1
        title_low = str(d["m"].get("title", "")).lower()
        tags = d["m"].get("tags") or []
        for term in q_terms:
            tf = sum(1 for tok in d["tokens"] if tok == term or term in tok)
            if tf > 0:
                df_t = df.get(term, 0)
                idf = math.log(1.0 + (n_docs - df_t + 0.5) / (df_t + 0.5))
                bm25 += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / max(1.0, avg_len)))))
            if term in title_low:
                bm25 += 1.4
            if any(term in tag for tag in tags):
                bm25 += 1.2
        sem = _cosine_sim(q_tri, d["trigrams"])
        proj_boost = 0.6 if (proj_low and str(d["m"].get("project", "")).lower() == proj_low) else 0.0
        total_score = bm25 + sem * 4.5 + proj_boost
        if bm25 > 0 or sem >= 0.14:
            scored.append({**d["m"], "score": round(total_score, 3)})

    scored.sort(key=lambda x: (x["score"], _ts_key(x.get("createdAt"))), reverse=True)
    return scored[:limit]


def build_memory_recall_snippet(
    project: str = "", override_dir: str | Path | None = None, max_items: int = 5
) -> dict[str, Any]:
    matches = search_memories(project=project, limit=max_items, override_dir=override_dir)
    if not matches:
        return {"text": "", "count": 0, "tokens": 0, "items": []}
    lines = [f"- [{m['kind']}] {m['title']}" for m in matches]
    text = f"[Claude-Mem ({len(matches)} recalled for {project or 'workspace'})]\n" + "\n".join(lines)
    return {
        "text": text,
        "count": len(matches),
        "tokens": estimate_tokens(text),
        "items": matches,
    }


def summarize_session_to_memory(
    analyzed_session: dict[str, Any] | None, override_dir: str | Path | None = None
) -> dict[str, Any] | None:
    if not analyzed_session or not analyzed_session.get("messages"):
        return None
    file_re = re.compile(r"\b[\w./-]+\.(?:ts|tsx|js|mjs|cjs|py|go|rs|sql|json|md|lua)\b")
    files: list[str] = []
    seen_files: set[str] = set()
    for m in analyzed_session["messages"]:
        for hit in file_re.findall(str(m.get("text") or "")):
            if hit not in seen_files:
                seen_files.add(hit)
                files.append(hit)

    last_reply = next(
        (m for m in reversed(analyzed_session["messages"]) if m.get("fromAgentId") != "user" and m.get("text")),
        None,
    )
    agents = ", ".join(a["name"] for a in (analyzed_session.get("agents") or [])[:6])
    file_list = ", ".join(files[:6])
    summary = analyzed_session.get("summary") or {}
    parts = [
        last_reply["text"][:260] if last_reply else analyzed_session.get("finding", ""),
        f"Files: {file_list}." if file_list else "",
        f"Agents: {agents} ({summary.get('agentTurns', 0)} turns, {summary.get('signalPct', 100)}% signal)." if agents else "",
    ]
    body = " ".join(p for p in parts if p)
    return add_memory(
        {
            "project": analyzed_session.get("project") or "workspace",
            "kind": "summary",
            "title": f"Session: {str(analyzed_session.get('title', ''))[:76]}",
            "body": body,
            "tags": ["session-summary"] + [Path(f).name for f in files[:3]],
            "source": "auto-summary",
        },
        override_dir,
    )


def maybe_extract_observation(
    *, text: str, project: str = "workspace", source: str = "hook", override_dir: str | Path | None = None
) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if len(raw) < 35 or len(raw) > 1800:
        return None

    has_file_ref = bool(re.search(r"[\w./-]+\.(?:ts|tsx|js|mjs|py|go|rs|sql|json|md)\b|`[^`]+`", raw))
    is_fix = bool(re.search(r"\b(?:fixed|patched|resolved|prevented|eliminated|bug|race|leak|timeout)\b", raw, re.I))
    is_decision = bool(re.search(r"\b(?:decided|architecture|migrated|replaced|switched to|using|enforced)\b", raw, re.I))
    is_gotcha = bool(re.search(r"\b(?:gotcha|warning|never|avoid|caveat|fails when|must not)\b", raw, re.I))

    if not has_file_ref or not (is_fix or is_decision or is_gotcha):
        return None

    kind = "gotcha" if is_gotcha else ("bugfix" if is_fix else "decision")
    first_sentence = re.split(r"(?<=[.!?])\s+|\n", raw)[0].strip()
    if len(first_sentence) < 24:
        return None

    return add_memory(
        {
            "project": project or "workspace",
            "kind": kind,
            "title": first_sentence[:90],
            "body": raw[:320],
            "tags": [kind, "auto"],
            "source": source,
        },
        override_dir,
    )


def get_seed_memories() -> list[dict[str, Any]]:
    return [
        {
            "project": "ledger-api",
            "kind": "bugfix",
            "title": "Guard JWT refresh rotation with per-family Redis NX lock and 10s sealed grace key",
            "body": "Concurrent tab refreshes hit `src/auth/refresh.ts:L74-L98` and tripped `ERR_TOKEN_REUSE`. Wrap rotation in `SET lock:rt:{familyId} NX PX 5000` with Lua compare-and-del in `finally` and AES-256-GCM sealed `rt:grace:{oldJti}`.",
            "tags": ["auth", "redis", "race-condition"],
            "source": "demo",
        },
        {
            "project": "payflow-worker",
            "kind": "pattern",
            "title": "Reuse lib/retry.ts backoffMs() and inject jitterFn for deterministic webhook tests",
            "body": "Stripe webhook duplicates are prevented via `ON CONFLICT (stripe_event_id) DO NOTHING` in `db/ledger.ts:L63`. Always pass injectable `jitterFn` so unit tests do not flake on random backoff delays.",
            "tags": ["stripe", "idempotency", "testing"],
            "source": "demo",
        },
        {
            "project": "global",
            "kind": "preference",
            "title": "Keep subagent handoffs terse with path:line citations and zero closing recaps",
            "body": "Reviewer subagents burned 50%+ of Opus output tokens on pleasantries and summaries. Enforce answer-first terse handoffs and Ponytail minimalism before creating new modules.",
            "tags": ["caveman", "ponytail", "protocol"],
            "source": "demo",
        },
    ]
