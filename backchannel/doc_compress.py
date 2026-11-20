"""Caveman-style deterministic Markdown / CLAUDE.md compressor with .bak.md backup."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .analyzer import estimate_tokens

_FILLER_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:please\s+make\s+sure\s+(?:that\s+)?you\s+|please\s+ensure\s+(?:that\s+)?|be\s+sure\s+to\s+|remember\s+to\s+)", re.I), ""),
    (re.compile(r"\b(?:in\s+order\s+to)\b", re.I), "to"),
    (re.compile(r"\b(?:due\s+to\s+the\s+fact\s+that|because\s+of\s+the\s+fact\s+that)\b", re.I), "because"),
    (re.compile(r"\b(?:at\s+this\s+point\s+in\s+time|at\s+the\s+present\s+time)\b", re.I), "now"),
    (re.compile(r"\b(?:for\s+the\s+purpose\s+of)\b", re.I), "for"),
    (re.compile(r"\b(?:in\s+the\s+event\s+that)\b", re.I), "if"),
    (re.compile(r"\b(?:it\s+is\s+important\s+to\s+note\s+that|note\s+that|keep\s+in\s+mind\s+that)\b[:,]?\s*", re.I), ""),
    (re.compile(r"\b(?:you\s+should\s+always|always\s+make\s+sure\s+to)\b", re.I), "always"),
    (re.compile(r"\b(?:basically|essentially|actually|simply|really|just|very|quite|extremely|obviously|clearly)\s+", re.I), ""),
    (re.compile(r"\b(?:implement\s+a\s+solution\s+for)\b", re.I), "fix"),
    (re.compile(r"\b(?:a\s+large\s+number\s+of|a\s+variety\s+of)\b", re.I), "many"),
    (re.compile(r"\b(?:utilize|utilization)\b", re.I), "use"),
    (re.compile(r"\b(?:subsequently)\b", re.I), "then"),
    (re.compile(r"\b(?:prior\s+to)\b", re.I), "before"),
    (re.compile(r"\b(?:regarding|concerning)\b", re.I), "on"),
    (re.compile(r"\b(?:additionally|furthermore|moreover),?\s+", re.I), ""),
    (re.compile(r"\b(?:in\s+summary|to\s+summarize|as\s+mentioned\s+(?:above|earlier)),?\s+", re.I), ""),
]

_STRUCTURAL_RE = re.compile(r"^\s*(?:#{1,6}\s|\||>|---|\*\*\*|```)")
_PROTECT_RE = re.compile(r"`[^`]+`|\[[^\]]+\]\([^)]+\)|https?://\S+")
_BULLET_RE = re.compile(r"^(\s*(?:[-*+]|\d+\.)\s+)(.*)$")


def _compress_prose_line(line: str) -> str:
    if _STRUCTURAL_RE.match(line):
        return line

    slots: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        idx = len(slots)
        slots.append(m.group(0))
        return f"\x00S{idx}\x00"

    safe = _PROTECT_RE.sub(_stash, line)
    bm = _BULLET_RE.match(safe)
    prefix = bm.group(1) if bm else ""
    orig_body = bm.group(2) if bm else safe
    body = orig_body

    for pat, rep in _FILLER_REPLACEMENTS:
        body = pat.sub(rep, body)

    body = re.sub(r"\s{2,}", " ", body)
    body = re.sub(r"\s+([.,;:])", r"\1", body).strip()
    if body and body[0].islower() and (not prefix or (orig_body and orig_body[0].isupper())):
        body = body[0].upper() + body[1:]

    restored = f"{prefix}{body}"
    return re.sub(r"\x00S(\d+)\x00", lambda m: slots[int(m.group(1))], restored)


def compress_markdown_text(markdown: str | None) -> dict[str, Any]:
    text_in = str(markdown or "")
    orig_tokens = estimate_tokens(text_in)
    lines = re.split(r"\r?\n", text_in)
    out: list[str] = []
    in_fence = False

    for line in lines:
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(_compress_prose_line(line))

    result_text = "\n".join(out).strip() + "\n"
    compressed_tokens = estimate_tokens(result_text)
    saved_tokens = max(0, orig_tokens - compressed_tokens)
    saved_pct = round((saved_tokens / orig_tokens) * 100, 1) if orig_tokens > 0 else 0.0

    return {
        "text": result_text,
        "origTokens": orig_tokens,
        "compressedTokens": compressed_tokens,
        "savedTokens": saved_tokens,
        "savedPct": saved_pct,
    }


def compress_markdown_file(file_path: str | Path, *, write: bool = True) -> dict[str, Any]:
    abs_path = Path(file_path).resolve()
    original = abs_path.read_text(encoding="utf-8")
    res = compress_markdown_text(original)

    backup_path: str | None = None
    if write and res["savedTokens"] > 0:
        ext = abs_path.suffix or ".md"
        bak = abs_path.with_name(f"{abs_path.stem}.bak{ext}")
        backup_path = str(bak)
        if not bak.exists():
            bak.write_text(original, encoding="utf-8")
        abs_path.write_text(res["text"], encoding="utf-8")

    return {**res, "filePath": str(abs_path), "backupPath": backup_path}
