"""Headroom-style local tool-output & log compressor, savings ledger, and budget tracker."""

from __future__ import annotations

import json
import math
import random
import re
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import estimate_tokens, iso_now
from .config import get_data_dir

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_ERROR_LINE_RE = re.compile(
    r"\b(?:error|err!|fail|failed|failing|exception|panic|traceback|assertionerror|typeerror|syntaxerror|"
    r"referenceerror|enoent|eperm|fatal|denied|timed out|expected:|received:|exit code [1-9])\b|^\s*[×✗✖✘]",
    re.IGNORECASE,
)
_PASS_LINE_RE = re.compile(r"^\s*(?:[✔✓]|ok\s+\d+|PASS\s+|✓\s|✔\s|---\s*PASS:)")
_INTERNAL_FRAME_RE = re.compile(r"^\s+at\s+.*(?:node_modules|node:internal|internal/modules)|^\s+File\s+\".*site-packages")


def _normalize_signature(line: str) -> str:
    s = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|s|kb|mb|b|%)\b", "<N>", line, flags=re.IGNORECASE)
    s = re.sub(r"\b0x[0-9a-f]+\b", "<HEX>", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b", "<TS>", s)
    s = re.sub(r"\b\d+\b", "<N>", s)
    return s.strip()


def compress_tool_output(
    raw_text: str | None, *, mode: str = "on", max_lines: int | None = None
) -> dict[str, Any]:
    text_in = "" if raw_text is None else str(raw_text)
    orig_bytes = len(text_in.encode("utf-8"))
    orig_tokens = estimate_tokens(text_in)

    if mode == "off" or len(text_in) < 180:
        line_count = len(text_in.splitlines()) if text_in else 0
        return {
            "text": text_in,
            "origBytes": orig_bytes,
            "compressedBytes": orig_bytes,
            "origTokens": orig_tokens,
            "compressedTokens": orig_tokens,
            "savedTokens": 0,
            "savedPct": 0.0,
            "origLines": line_count,
            "compressedLines": line_count,
            "rulesApplied": [],
        }

    rules_applied: list[str] = []
    seen_rules: set[str] = set()

    def add_rule(r: str) -> None:
        if r not in seen_rules:
            seen_rules.add(r)
            rules_applied.append(r)

    cleaned = _ANSI_RE.sub("", text_in)
    if cleaned != text_in:
        add_rule("strip-ansi")

    no_spinner = re.sub(r"[^\n]*\r(?!\n)", "", cleaned)
    if no_spinner != cleaned:
        cleaned = no_spinner
        add_rule("strip-spinner-frames")

    lines = re.split(r"\r?\n", cleaned)
    orig_lines = len(lines)
    out: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            i += 1
            continue

        if _ERROR_LINE_RE.search(line):
            out.append(line)
            i += 1
            continue

        if _INTERNAL_FRAME_RE.search(line):
            j = i
            while j < len(lines) and _INTERNAL_FRAME_RE.search(lines[j]):
                j += 1
            count = j - i
            if count >= 2:
                out.append(f"    ... ({count} internal runtime stack frames collapsed)")
                add_rule("collapse-stack-internals")
                i = j
                continue

        if _PASS_LINE_RE.search(line):
            j = i
            while j < len(lines) and _PASS_LINE_RE.search(lines[j]) and not _ERROR_LINE_RE.search(lines[j]):
                j += 1
            count = j - i
            threshold = 3 if mode == "aggressive" else 4
            if count >= threshold:
                out.append(lines[i])
                out.append(f"... ({count - 2} passing test lines collapsed)")
                out.append(lines[j - 1])
                add_rule("collapse-passing-tests")
                i = j
                continue

        sig = _normalize_signature(line)
        if len(sig) >= 12:
            j = i + 1
            while j < len(lines) and not _ERROR_LINE_RE.search(lines[j]) and _normalize_signature(lines[j]) == sig:
                j += 1
            count = j - i
            if count >= 3:
                out.append(line)
                out.append(f"... ({count - 1} similar lines collapsed)")
                add_rule("dedupe-repeated-lines")
                i = j
                continue

        out.append(line)
        i += 1

    limit = max_lines or (45 if mode == "aggressive" else 90)
    final_lines = out
    if len(out) > limit:
        head_n = math.floor(limit * 0.35)
        tail_n = math.floor(limit * 0.35)
        head = out[:head_n]
        tail = out[len(out) - tail_n :]
        middle = out[head_n : len(out) - tail_n]
        preserved_errors = [ln for ln in middle if _ERROR_LINE_RE.search(ln)][: math.floor(limit * 0.3)]
        omitted = len(middle) - len(preserved_errors)
        final_lines = list(head)
        if preserved_errors:
            final_lines.append("... (middle output trimmed; errors preserved):")
            final_lines.extend(preserved_errors)
        final_lines.append(f"... ({omitted} middle lines omitted by headroom compressor)")
        final_lines.extend(tail)
        add_rule("bound-window-preserve-errors")

    result_text = "\n".join(final_lines).strip()
    compressed_bytes = len(result_text.encode("utf-8"))
    compressed_tokens = estimate_tokens(result_text)
    saved_tokens = max(0, orig_tokens - compressed_tokens)
    saved_pct = round((saved_tokens / orig_tokens) * 100, 1) if orig_tokens > 0 else 0.0

    return {
        "text": result_text,
        "origBytes": orig_bytes,
        "compressedBytes": compressed_bytes,
        "origTokens": orig_tokens,
        "compressedTokens": compressed_tokens,
        "savedTokens": saved_tokens,
        "savedPct": saved_pct,
        "origLines": orig_lines,
        "compressedLines": len(final_lines),
        "rulesApplied": rules_applied,
    }


def get_savings_ledger_path(override_dir: str | Path | None = None) -> Path:
    return get_data_dir(override_dir) / "savings.jsonl"


def record_compression_saving(
    entry: dict[str, Any], override_dir: str | Path | None = None
) -> dict[str, Any]:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    record = {
        "id": f"cmp-{int(time.time() * 1000)}-{suffix}",
        "timestamp": iso_now(),
        "source": entry.get("source") or "cli",
        "label": entry.get("label") or "tool output",
        "mode": entry.get("mode") or "on",
        "origTokens": entry.get("origTokens") or 0,
        "compressedTokens": entry.get("compressedTokens") or 0,
        "savedTokens": entry.get("savedTokens") or 0,
        "savedPct": entry.get("savedPct") or 0,
        "rulesApplied": entry.get("rulesApplied") or [],
    }
    try:
        data_dir = get_data_dir(override_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        with get_savings_ledger_path(override_dir).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return record


def load_savings_ledger(override_dir: str | Path | None = None, limit: int = 40) -> list[dict[str, Any]]:
    path = get_savings_ledger_path(override_dir)
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        items: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
        items.reverse()
        return items
    except Exception:
        return []


def _parse_iso_ms(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000.0
    except Exception:
        return 0.0


def compute_headroom_summary(
    sessions: list[dict[str, Any]] | None = None,
    ledger: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sessions = sessions or []
    ledger = ledger or []
    config = config or {}
    now_ms = time.time() * 1000.0
    ms_5h = 5 * 60 * 60 * 1000.0
    ms_7d = 7 * 24 * 60 * 60 * 1000.0

    spend_5h = spend_7d = 0.0
    tokens_5h = tokens_7d = sessions_5h = sessions_7d = 0
    total_in = total_out = total_cache = 0
    total_cost = total_chatter_tax = 0.0

    for s in sessions:
        ts = _parse_iso_ms(s.get("startedAt"))
        age = now_ms - ts
        sm = s.get("summary") or {}
        total_in += sm.get("totalInputTokens") or 0
        total_out += sm.get("totalOutputTokens") or 0
        total_cache += sm.get("totalCacheReadTokens") or 0
        total_cost += sm.get("totalCostUsd") or 0.0
        total_chatter_tax += sm.get("chatterTaxUsd") or 0.0

        if 0 <= age <= ms_5h:
            spend_5h += sm.get("totalCostUsd") or 0.0
            tokens_5h += sm.get("totalTokens") or 0
            sessions_5h += 1
        if 0 <= age <= ms_7d:
            spend_7d += sm.get("totalCostUsd") or 0.0
            tokens_7d += sm.get("totalTokens") or 0
            sessions_7d += 1

    total_read = total_in + total_cache
    cache_hit_pct = round((total_cache / total_read) * 100, 1) if total_read > 0 else 0.0
    est_cache_savings = round((total_cache / 1_000_000) * 2.7, 2)

    ledger_orig = sum(r.get("origTokens") or 0 for r in ledger)
    ledger_saved = sum(r.get("savedTokens") or 0 for r in ledger)
    ledger_saved_pct = round((ledger_saved / ledger_orig) * 100, 1) if ledger_orig > 0 else 0.0

    return {
        "window5h": {
            "spendUsd": round(spend_5h, 2),
            "budgetUsd": config.get("budget5hUsd") or 25,
            "tokens": tokens_5h,
            "sessions": sessions_5h,
        },
        "window7d": {
            "spendUsd": round(spend_7d, 2),
            "budgetUsd": config.get("budget7dUsd") or 150,
            "tokens": tokens_7d,
            "sessions": sessions_7d,
        },
        "cache": {
            "cacheReadTokens": total_cache,
            "inputTokens": total_in,
            "cacheHitPct": cache_hit_pct,
            "estCacheSavingsUsd": est_cache_savings,
        },
        "compressor": {
            "runs": len(ledger),
            "origTokens": ledger_orig,
            "savedTokens": ledger_saved,
            "savedPct": ledger_saved_pct,
            "recent": ledger[:8],
        },
        "totals": {
            "totalCostUsd": round(total_cost, 2),
            "chatterTaxUsd": round(total_chatter_tax, 2),
            "totalOutputTokens": total_out,
        },
    }
